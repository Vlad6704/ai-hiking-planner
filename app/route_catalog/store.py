"""Transactional catalog writes and parameterized read-only route queries."""

import json
import os
import sqlite3
from contextlib import closing, contextmanager
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app.models.contracts import RouteDetails, RouteQuery
from app.route_catalog.models import CatalogRoute, CatalogVariant, content_hash


def database_path():
    default = Path(__file__).resolve().parents[2] / "data/routes.sqlite3"
    return Path(os.getenv("ROUTE_CATALOG_DB", str(default))).resolve()


def utcnow():
    return datetime.now(UTC).isoformat()


def local_day(instant):
    return datetime.fromisoformat(instant).astimezone(ZoneInfo("Europe/Warsaw")).date().isoformat()


class CatalogStore:
    def __init__(self, path: Path, *, clock=None):
        self.path = Path(path).resolve()
        self.clock = clock or utcnow
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=10)) as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise ValueError("unsupported_catalog_schema")
            if version == 0:
                connection.execute("PRAGMA journal_mode=WAL")
                connection.executescript(Path(__file__).with_name("schema.sql").read_text(encoding="utf-8"))

    @contextmanager
    def writer(self):
        with closing(sqlite3.connect(self.path, timeout=10)) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    def connect_readonly(self):
        connection = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        return connection

    def state(self):
        with closing(self.connect_readonly()) as connection:
            state = dict(connection.execute("SELECT * FROM catalog_state WHERE id=1").fetchone())
        state["stale"] = (state["last_outcome"] != "complete" or not state["last_success_at"]
                          or local_day(state["last_success_at"]) != local_day(self.clock()))
        return state

    def records(self):
        with closing(self.connect_readonly()) as connection:
            rows = connection.execute("SELECT route_id,payload FROM routes").fetchall()
        records = {}
        for row in rows:
            data = json.loads(row["payload"])
            data["variants"] = [CatalogVariant(**item) for item in data["variants"]]
            records[row["route_id"]] = CatalogRoute(**data)
        return records

    def active_ids(self):
        with closing(self.connect_readonly()) as connection:
            return {row[0] for row in connection.execute('SELECT route_id FROM routes WHERE active=1')}

    def claim_refresh(self, day, owner, lease_until, force=False, now=None):
        now = now or utcnow()
        with self.writer() as connection:
            state = connection.execute("SELECT * FROM catalog_state WHERE id=1").fetchone()
            active_owner = state["owner"] and state["lease_until"] and datetime.fromisoformat(state["lease_until"]) > datetime.fromisoformat(now)
            if active_owner or (not force and state["owner"] is None and state["last_attempt_day"] == day):
                return False
            connection.execute("UPDATE catalog_state SET owner=?,lease_until=?,last_attempt_day=? WHERE id=1",
                               (owner, lease_until, day))
            connection.execute("INSERT INTO catalog_refresh_runs VALUES(?,?,?,?,?,?)",
                               (owner, "manual" if force else "automatic", now, None, "running", "{}"))
        return True

    def fail_refresh(self, owner, error, checked_at):
        report = dict(run_id=owner, outcome="failed", discovered=0, parsed=0, errors=[dict(error=error)])
        with self.writer() as connection:
            state = connection.execute("SELECT owner FROM catalog_state WHERE id=1").fetchone()
            if state["owner"] != owner:
                raise ValueError("refresh_ownership_lost")
            connection.execute("UPDATE catalog_state SET owner=NULL,lease_until=NULL,last_outcome='failed',run_id=? WHERE id=1", (owner,))
            connection.execute("UPDATE catalog_refresh_runs SET finished_at=?,outcome='failed',report=? WHERE run_id=?",
                               (checked_at, json.dumps(report), owner))
        return report

    def has_usable(self):
        with closing(self.connect_readonly()) as connection:
            return connection.execute("SELECT 1 FROM routes r JOIN route_variants v ON v.route_id=r.route_id WHERE r.active=1 AND v.active=1 LIMIT 1").fetchone() is not None

    def publish(self, routes, entries, *, complete, checked_at, run_id, errors, trigger="manual", owned=False):
        if complete and not entries:
            raise ValueError("empty_catalog")
        report = dict(run_id=run_id, discovered=len(entries), parsed=len(routes), added=0,
                      changed=0, unchanged=0, inactive=0, errors=errors,
                      warnings={route.route_id: route.warnings for route in routes if route.warnings},
                      outcome="complete" if complete else "partial")
        with self.writer() as connection:
            state = connection.execute("SELECT * FROM catalog_state WHERE id=1").fetchone()
            if ((owned and (state["owner"] != run_id or not state["lease_until"]
                            or datetime.fromisoformat(state["lease_until"]) <= datetime.fromisoformat(checked_at)))
                    or (state["owner"] is not None and state["owner"] != run_id)):
                raise ValueError("refresh_ownership_lost")
            for route in routes:
                old = connection.execute("SELECT * FROM routes WHERE route_id=?", (route.route_id,)).fetchone()
                digest = content_hash(route)
                changed = old is None or old["content_hash"] != digest or not old["active"]
                report["added" if old is None else "changed" if changed else "unchanged"] += 1
                payload = json.dumps(asdict(route), ensure_ascii=False)
                connection.execute("""INSERT INTO routes(route_id,payload,content_hash,created_at,updated_at,
                    last_checked_at,last_seen_at,parse_status) VALUES(?,?,?,?,?,?,?,?)
                    ON CONFLICT(route_id) DO UPDATE SET payload=excluded.payload,content_hash=excluded.content_hash,
                    updated_at=excluded.updated_at,last_checked_at=excluded.last_checked_at,
                    last_seen_at=excluded.last_seen_at,active=1,parse_status=excluded.parse_status,last_error=NULL""",
                    (route.route_id, payload, digest, old["created_at"] if old else checked_at,
                     checked_at if changed else old["updated_at"], checked_at, checked_at,
                     "partial" if route.warnings else "ready"))
                if changed:
                    connection.execute("UPDATE route_variants SET active=0 WHERE route_id=?", (route.route_id,))
                    for variant in route.variants:
                        connection.execute("""INSERT INTO route_variants VALUES(?,?,?,?,?,?,?,?,?,?,1)
                            ON CONFLICT(variant_id) DO UPDATE SET variant_key=excluded.variant_key,name=excluded.name,
                            distance_m=excluded.distance_m,duration_minutes=excluded.duration_minutes,
                            ascent_m=excluded.ascent_m,descent_m=excluded.descent_m,
                            difficulty=excluded.difficulty,layout=excluded.layout,active=1""",
                            (variant.variant_id, route.route_id, variant.key, variant.name, variant.distance_m,
                             variant.duration_minutes, variant.ascent_m, variant.descent_m, variant.difficulty, variant.layout))
                    connection.execute("DELETE FROM routes_fts WHERE route_id=?", (route.route_id,))
                    connection.execute("INSERT INTO routes_fts VALUES(?,?,?,?,?,?)",
                                       (route.route_id, route.name, route.description, route.instructions,
                                        route.points_of_interest, route.cautions))
            parsed = {route.route_id for route in routes}
            errors_by_id = {item.get("route_id"): item.get("error", "source_unavailable") for item in errors}
            for entry in entries:
                if entry["route_id"] in parsed:
                    continue
                old = connection.execute("SELECT 1 FROM routes WHERE route_id=?", (entry["route_id"],)).fetchone()
                if old is None:
                    stub = CatalogRoute(entry["route_id"], entry["name"], entry["url"], entry.get("category", "PR"), "")
                    connection.execute("INSERT INTO routes(route_id,payload,content_hash,created_at,updated_at,last_seen_at,parse_status,last_error) VALUES(?,?,?,?,?,?,?,?)",
                                       (stub.route_id, json.dumps(asdict(stub)), content_hash(stub), checked_at, checked_at,
                                        checked_at, "error", errors_by_id.get(stub.route_id)))
                else:
                    connection.execute("UPDATE routes SET last_seen_at=?,last_error=?,parse_status='stale' WHERE route_id=?",
                                       (checked_at, errors_by_id.get(entry["route_id"]), entry["route_id"]))
            if complete:
                present = {entry["route_id"] for entry in entries}
                missing = [row[0] for row in connection.execute("SELECT route_id FROM routes WHERE active=1") if row[0] not in present]
                for route_id in missing:
                    connection.execute("UPDATE routes SET active=0,updated_at=? WHERE route_id=?", (checked_at, route_id))
                    connection.execute("UPDATE route_variants SET active=0 WHERE route_id=?", (route_id,))
                    connection.execute("DELETE FROM routes_fts WHERE route_id=?", (route_id,))
                report["inactive"] = len(missing)
            connection.execute("UPDATE catalog_state SET last_attempt_day=?,last_success_at=?,last_outcome=?,owner=NULL,lease_until=NULL,run_id=? WHERE id=1",
                               (local_day(checked_at), checked_at if complete else state["last_success_at"], report["outcome"], run_id))
            connection.execute("""INSERT INTO catalog_refresh_runs VALUES(?,?,?,?,?,?)
                ON CONFLICT(run_id) DO UPDATE SET finished_at=excluded.finished_at,
                outcome=excluded.outcome,report=excluded.report""",
                (run_id, trigger, checked_at, checked_at, report["outcome"], json.dumps(report)))
        return report

    def _result(self, row, state, full=False):
        data = json.loads(row["payload"])
        return RouteDetails(route_id=row["variant_id"], source_route_id=row["route_id"], variant_id=row["variant_id"],
                    name=data["name"] + " — " + row["name"], difficulty=row["difficulty"],
                    distance_km=row["distance_m"] / 1000 if row["distance_m"] is not None else None,
                    duration_hours=row["duration_minutes"] / 60 if row["duration_minutes"] is not None else None,
                    elevation_gain_m=row["ascent_m"], elevation_loss_m=row["descent_m"], layout=row["layout"],
                    description=data["description"] if full else data["description"][:600],
                    instructions=data["instructions"] if full else None,
                    points_of_interest=data["points_of_interest"] if full else None,
                    full_text=data["full_text"] if full else None,
                    constraints=[data["cautions"]] if data["cautions"] else [], source=data["url"],
                    source_language=data["source_language"], content_hash=row["content_hash"],
                    created_at=row["created_at"], updated_at=row["updated_at"], last_checked_at=row["last_checked_at"],
                    snippet=row["excerpt"], catalog_stale=state["stale"] or row["parse_status"] == "stale",
                    catalog_run_id=state["run_id"], parse_warnings=data["warnings"]).model_dump(mode='json')

    def search(self, query: RouteQuery) -> list[dict]:
        terms, arguments = ["r.active=1", "v.active=1"], []
        if query.location and query.location.casefold() != "picos de europa":
            return []
        if query.difficulty:
            terms.append("v.difficulty=?"); arguments.append(query.difficulty.casefold())
        bounds = [("min_km", "distance_m", ">=", 1000), ("max_km", "distance_m", "<=", 1000),
                  ("min_hours", "duration_minutes", ">=", 60), ("max_hours", "duration_minutes", "<=", 60),
                  ("min_gain_m", "ascent_m", ">=", 1), ("max_gain_m", "ascent_m", "<=", 1),
                  ("min_loss_m", "descent_m", ">=", 1), ("max_loss_m", "descent_m", "<=", 1)]
        for name, column, operator, factor in bounds:
            value = getattr(query, name)
            if value is not None:
                terms.append(f"v.{column}{operator}?"); arguments.append(value * factor)
        joined = ""
        excerpt = "NULL"
        if query.keywords:
            words = ['"' + word.replace('"', '""') + '"' + ('*' if query.prefix else '') for word in query.keywords]
            expression = (" AND " if query.keyword_match == "all" else " OR ").join(words)
            terms.append("routes_fts MATCH ?"); arguments.append(expression)
            joined = " JOIN routes_fts ON routes_fts.route_id=r.route_id"
            excerpt = "snippet(routes_fts,-1,'[',']',' ... ',24)"
        orders = {"name": "lower(json_extract(r.payload,'$.name'))", "distance": "v.distance_m",
                  "duration": "v.duration_minutes", "ascent": "v.ascent_m", "descent": "v.descent_m"}
        order = orders.get(query.sort)
        order = (f"{order} IS NULL,{order}," if order else "bm25(routes_fts)," if query.keywords else "") + "v.variant_id"
        sql = f"SELECT r.*,v.*,{excerpt} AS excerpt FROM routes r JOIN route_variants v ON v.route_id=r.route_id{joined} WHERE {' AND '.join(terms)} ORDER BY {order} LIMIT ? OFFSET ?"
        with closing(self.connect_readonly()) as connection:
            rows = connection.execute(sql, [*arguments, query.limit, query.offset]).fetchall()
        state = self.state()
        return [self._result(row, state) for row in rows]

    def details(self, route_id: str) -> dict:
        with closing(self.connect_readonly()) as connection:
            rows = connection.execute("SELECT r.*,v.*,NULL AS excerpt FROM routes r JOIN route_variants v ON v.route_id=r.route_id WHERE r.active=1 AND v.active=1 AND (v.variant_id=? OR r.route_id=?)",
                                      (route_id, route_id)).fetchall()
        if not rows:
            raise ValueError("route_not_found")
        if len(rows) > 1:
            raise ValueError("variant_required")
        return self._result(rows[0], self.state(), full=True)
