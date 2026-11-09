"""Extract official route pages without guessing ambiguous measurements."""

import re
import unicodedata
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

from app.route_catalog.models import CatalogRoute, CatalogVariant

INDEX_URL = "https://www.miteco.gob.es/es/parques-nacionales-oapn/red-parques-nacionales/parques-nacionales/picos-europa/guia-visitante/itinerarios.html"


def fold(text):
    return "".join(c for c in unicodedata.normalize("NFD", text.casefold()) if unicodedata.category(c) != "Mn")


class Document(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.parts, self.links = [], []
        self.ignored = 0
        self.anchor = None
        self.anchor_text = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self.ignored += 1
        if tag == "a":
            self.anchor = dict(attrs).get("href")
            self.anchor_text = []

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript"):
            self.ignored = max(0, self.ignored - 1)
        if tag == "a" and self.anchor:
            self.links.append((self.anchor, " ".join(" ".join(self.anchor_text).split())))
            self.anchor = None

    def handle_data(self, data):
        if not self.ignored:
            self.parts.append(data)
            if self.anchor:
                self.anchor_text.append(data)

    @property
    def text(self):
        return " ".join(" ".join(self.parts).split())


def allowed_url(url, origin=INDEX_URL):
    parsed, base = urlparse(url), urlparse(origin)
    return parsed.scheme == "https" and parsed.hostname == base.hostname and not parsed.username and not parsed.password


def discover_routes(html: str, index_url: str = INDEX_URL) -> list[dict]:
    found = {}
    for href, label in Document(html).links:
        match = re.search(r"\b(PR|GR)[ -]*PNPE\s*[- ]?\s*(\d+)\b", label, re.I)
        url = urljoin(index_url, href).split("#", 1)[0]
        if match and allowed_url(url, index_url) and urlparse(url).path.endswith(".html"):
            route_id = f"{match[1].upper()}-PNPE-{int(match[2])}"
            found.setdefault(route_id, dict(route_id=route_id, name=label.split(":", 1)[-1].strip(),
                                            url=url, category=match[1].upper()))
    return list(found.values())


LABELS = {
    "length": r"longitud|length",
    "elevation": r"desnive\s*l(?:es)?(?:\s+acumulados?)?|difference in altitude",
    "duration": r"duracion|duration",
    "difficulty": r"dificultad|difficulty",
    "description": r"descripcion|description",
    "instructions": r"como hacer la ruta|how to make the trail",
    "points": r"preste atencion a|interesting places",
    "cautions": r"precauciones|caution notes",
}
LABEL_PATTERN = re.compile(r"\b(" + "|".join(LABELS.values()) + r")\s*(?:\([^)]*\))?\s*:")
NUMBER = r"\d+(?:[.,']\d+)?"


def sections(text):
    normalized = fold(text)
    end = re.search(r"guia del visitante|visitor guide", normalized)
    if end:
        text, normalized = text[:end.start()], normalized[:end.start()]
    matches = list(LABEL_PATTERN.finditer(normalized))
    result = {}
    for index, match in enumerate(matches):
        key = next(key for key, pattern in LABELS.items() if re.fullmatch(pattern, match[1]))
        result.setdefault(key, text[match.end():matches[index + 1].start() if index + 1 < len(matches) else len(text)].strip())
    start = matches[0].start() if matches else 0
    return result, text[start:]


def decimal(text):
    return float(text.replace(",", ".").replace("'", "."))


def kind(label):
    label = fold(label)
    if re.search(r"\blargo\b|\blong\b", label): return "long"
    if re.search(r"\bcorto\b|\bshort\b", label): return "short"
    if re.search(r"ida y vuelta|round.trip|out.and.back|return trip", label): return "return"
    if re.search(r"circuit|circular", label): return "circuit"
    if re.search(r"complet|full route", label): return "full"
    if re.search(r"solo ida|recorrido de ida|\(ida\b|one.way|sentido ascendente|subida\W*$|ascenso\W*$", label): return "outbound"
    if re.search(r"sentido descendente|descenso\W*$|inbound", label): return "inbound"
    return "main"


def measurements(text, duration=False):
    # A new starting-point heading can follow a measurement without a slash.
    text = re.sub(r"(?i)\s*((?:partiendo de|starting (?:at|from))\s+[^:;/]+:)", r"; \1", text)
    pattern = (rf"({NUMBER})\s*(?:h\b\.?|hours?)(?:\s*(\d+)\s*min(?:utes?)?\.?)?"
               if duration else rf"({NUMBER})\s*(?:km\b|kilometres?)\.?")
    matches = list(re.finditer(pattern, fold(text)))
    result = []
    for index, match in enumerate(matches):
        prefix = text[:match.start()]
        tail = text[match.end():matches[index + 1].start() if index + 1 < len(matches) else len(text)]
        after = re.split(r"[/;]", tail, maxsplit=1)[0].strip(" .")
        before = re.split(r"[/;]", prefix)[-1]
        # Starting-point prefixes qualify both the outbound and return alternatives.
        origins = re.findall(r"(?:partiendo de|starting (?:at|from))\s+([^:]+):", fold(prefix))
        origin = re.sub(r"[^a-z0-9]+", "-", origins[-1]).strip("-") if origins else ""
        label = (before + " " + after).strip() if ":" in before else after
        category = kind(label)
        key = (origin + "-" if origin else "") + category
        value = round(decimal(match[1]) * (60 if duration else 1000))
        if duration and match[2]: value += int(match[2])
        result.append(dict(value=value, key=key, label=label, kind=category))
    return result


def words(label):
    return set(path_words(label))


def path_words(label):
    ignored = set('recorrido trayecto tramo sentido desde hasta entre solo ida vuelta partiendo complete route full linear hours minutos minutes etapa ruta completa completo puerto del los las station starting from circuito ascent descent ascenso descenso subida bajada'.split())
    return [word for word in re.findall(r'[a-z]{3,}', fold(label)) if word not in ignored]


def same_direction(left, right):
    def endpoints(label):
        parts = re.split(r'(?<=[a-z])\s*[-–—]\s*(?=[a-z])', fold(label))
        if len(parts) < 2:
            return None
        start, end = path_words(parts[0]), path_words(parts[-1])
        return (start[-1], end[0]) if start and end else None
    left_endpoints, right_endpoints = endpoints(left), endpoints(right)
    if left_endpoints and right_endpoints and left_endpoints != right_endpoints:
        return False
    left, right = path_words(left), path_words(right)
    common = set(left) & set(right)
    return len(common) < 2 or [word for word in left if word in common] == [word for word in right if word in common]


def choose_duration(distance, times, distances):
    times = [item for item in times if same_direction(distance['label'], item['label'])]
    if (distance['kind'] == 'outbound' and any(item['kind'] == 'inbound' for item in times)
            and not re.search(r'ascendente|ascenso|subida', fold(distance['label']))):
        return None
    compatible = {'return': {'full'}, 'full': {'return'}, 'circuit': {'full'}}
    if distance['kind'] != 'main':
        allowed = {distance['kind']} | compatible.get(distance['kind'], set())
        if len(distances) == 1 or distance['kind'] in ('outbound', 'inbound'):
            allowed.add('main')
        times = [item for item in times if item['kind'] in allowed]
    elif any(item['kind'] == 'return' for item in distances):
        times = [item for item in times if item['kind'] in ('main', 'outbound')]
    candidates = [item for item in times if item["key"] == distance["key"]]
    if distance['kind'] != 'main' and len(candidates) == 1 and sum(item['key'] == distance['key'] for item in distances) == 1:
        return candidates[0]["value"]
    if len(times) == 1 and len(distances) == 1:
        if times[0]['kind'] == 'main' or distance['kind'] == times[0]['kind']:
            return times[0]["value"]
    candidates = [item for item in times if item['kind'] in compatible.get(distance['kind'], set())]
    if len(candidates) == 1:
        return candidates[0]['value']
    scored = [(len(words(distance["label"]) & words(item["label"])), item) for item in times]
    best = max((score for score, _ in scored), default=0)
    winners = [item for score, item in scored if score == best and score >= 2]
    return winners[0]["value"] if len(winners) == 1 else None


def elevation(text, category, variant_label=""):
    if (len(re.findall(r'\d[\d.,]*\s*m\b', fold(text))) == 1
            and kind(text) in ('return', 'full', 'circuit') and category in ('outbound', 'main')):
        return None, None
    if re.search(r"ascenso o descenso|ascent or descent", fold(text)) and category != 'return':
        return None, None
    groups = re.split(r"[/;]", text)
    if re.search(r'\w+\s+-\s+\w+', text):
        # Named segments need endpoint evidence, including direction. Shared
        # page context alone cannot assign their heights to another variant.
        groups = [group for group in groups if len(words(variant_label) & words(group)) >= 2
                  and same_direction(variant_label, group)]
        if not groups:
            return None, None
        text = ' / '.join(groups)
    if len(groups) > 1:
        if category in ('circuit', 'full'):
            specific = [group for group in groups if kind(group) in ('circuit', 'full')]
            if specific:
                groups = specific
        elif category not in ('return',):
            groups = [group for group in groups if not re.search(r'ida y vuelta|en el regreso', fold(group))]
        text = ' / '.join(groups)
        scores = [(len(words(variant_label) & words(group)), group) for group in groups]
        best = max((score for score, _ in scores), default=0)
        winners = [group for score, group in scores if score == best and score >= 2]
        if len(winners) == 1:
            text = winners[0]
    normalized = fold(text)
    values = list(re.finditer(r"(\d+(?:[.,]\d{3})*)\s*m\b\.?", normalized))
    if len(values) > 2:
        return None, None
    up = down = None
    for index, match in enumerate(values):
        label = normalized[match.end():values[index + 1].start() if index + 1 < len(values) else len(normalized)]
        label = label.split("/", 1)[0]
        value = int(match[1].replace(".", "").replace(",", ""))
        ascent = bool(re.search(r"subida|ascenso|ascendente|ascent", label))
        descent = bool(re.search(r"bajada|descenso|descendente|descent", label))
        if category == 'outbound' and kind(label) == 'return':
            continue
        if ascent: up = value
        if descent: down = value
    if category == "outbound" and len(values) == 1 and up is not None and down is not None:
        down = None
    if category == "return" and len(values) == 1 and (up is not None or down is not None):
        up = down = up if up is not None else down
    if category == 'return' and up is not None and down is not None and up != down:
        return None, None
    return up, down


def parse_route(html: str, entry: dict) -> CatalogRoute:
    document = Document(html)
    fields, full_text = sections(document.text)
    if not fields.get("description") or not fields.get("length"):
        raise ValueError("route_sections_missing")
    distances = measurements(fields["length"])
    times = measurements(fields.get("duration", ""), duration=True)
    if not distances:
        raise ValueError("route_distance_missing")
    route = CatalogRoute(route_id=entry["route_id"], name=entry["name"], url=entry["url"],
                         category=entry.get("category", "PR"), description=fields["description"],
                         instructions=fields.get("instructions", ""), points_of_interest=fields.get("points", ""),
                         cautions=fields.get("cautions", ""), full_text=full_text, raw_metrics={k: fields.get(k, "") for k in ("length", "duration", "elevation", "difficulty")})
    for href, label in document.links:
        if fold(label) in ("mapa de la ruta", "route map"): route.map_url = urljoin(entry["url"], href)
        if "perfil" in fold(label): route.profile_url = urljoin(entry["url"], href)
    difficulty_text = fold(fields.get("difficulty", ""))
    levels = [(word, level) for word, level in (("baja", "easy"), ("low", "easy"), ("media", "moderate"), ("moderate", "moderate"), ("alta", "hard"), ("high", "hard")) if re.search(r"\b" + word + r"\b", difficulty_text)]
    for index, distance in enumerate(distances):
        key = distance["key"]
        if sum(item["key"] == key for item in distances) > 1:
            key = re.sub(r"[^a-z0-9]+", "-", fold(distance["label"])).strip("-")[:100] or f"variant-{index + 1}"
        minutes = choose_duration(distance, times, distances)
        up, down = elevation(fields.get("elevation", ""), distance["kind"], distance["label"])
        level = levels[0][1] if len(set(value for _, value in levels)) == 1 else "unknown"
        if len(set(value for _, value in levels)) == 2 and "ida y vuelta" in difficulty_text:
            level = levels[-1][1] if distance["kind"] == "return" else levels[0][1]
        if minutes is None: route.warnings.append(f"Duration is ambiguous or missing for {key}")
        layout = "out_and_back" if distance["kind"] == "return" else "circular" if distance["kind"] in ("long", "short", "circuit") else "unknown"
        route.variants.append(CatalogVariant(f"{route.route_id}:{key}", key, distance["label"] or "Main route", distance["value"], minutes, up, down, level, layout))
    if len({v.variant_id for v in route.variants}) != len(route.variants):
        raise ValueError("ambiguous_variant_identity")
    return route
