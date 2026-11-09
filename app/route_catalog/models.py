"""Normalized source records, separate from agent-facing tool contracts."""

import hashlib
import json
from dataclasses import asdict, dataclass, field

PARSER_VERSION = "2"


@dataclass
class CatalogVariant:
    variant_id: str
    key: str
    name: str
    distance_m: int | None
    duration_minutes: int | None
    ascent_m: int | None
    descent_m: int | None
    difficulty: str
    layout: str = "unknown"


@dataclass
class CatalogRoute:
    route_id: str
    name: str
    url: str
    category: str
    description: str
    instructions: str = ""
    points_of_interest: str = ""
    cautions: str = ""
    full_text: str = ""
    source_language: str = "es"
    map_url: str | None = None
    profile_url: str | None = None
    raw_metrics: dict = field(default_factory=dict)
    variants: list[CatalogVariant] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    parser_version: str = PARSER_VERSION
    etag: str | None = None
    last_modified: str | None = None


def content_hash(route: CatalogRoute) -> str:
    data = asdict(route)
    data.pop("parser_version", None)
    data.pop("etag", None)
    data.pop("last_modified", None)
    data["variants"] = sorted(data["variants"], key=lambda row: row["variant_id"])

    def normalize(value):
        if isinstance(value, str):
            return " ".join(value.split())
        if isinstance(value, list):
            return [normalize(item) for item in value]
        if isinstance(value, dict):
            return {key: normalize(item) for key, item in value.items()}
        return value

    return hashlib.sha256(json.dumps(normalize(data), sort_keys=True, ensure_ascii=False).encode()).hexdigest()
