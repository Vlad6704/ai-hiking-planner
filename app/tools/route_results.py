"""Compact route content for the model while retaining original audit data."""


SUMMARY_FIELDS = (
    "route_id", "name", "difficulty", "distance_km", "duration_hours",
    "elevation_gain_m", "elevation_loss_m", "snippet",
)
DETAIL_FIELDS = SUMMARY_FIELDS + (
    "description", "instructions", "points_of_interest", "constraints",
    "source", "source_language", "layout", "parse_warnings",
)


def route_model_result(result, *, details=False):
    compact = {key: value for key, value in result.items() if key != "metadata"}
    if result["status"] == "error":
        return compact
    fields = DETAIL_FIELDS if details else SUMMARY_FIELDS
    rows = [result["data"]] if details else result["data"]
    projected = [
        {key: row[key] for key in fields
         if key in row and not (key == "snippet" and row[key] is None)}
        for row in rows
    ]
    compact["data"] = projected[0] if details else projected
    return compact
