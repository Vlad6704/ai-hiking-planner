import importlib


def page(length="5 km (long loop); 3 km (short loop)", duration="2.5 h (long loop); 1 h (short loop)"):
    return f'''<html><h1>PR-PNPE 2 — Lake route</h1><p>Length: {length}</p>
    <p>Difference in altitude: 50 m ascent and descent</p><p>Duration: {duration}</p>
    <p>Difficulty: Low</p><p>Description: A waterfall beside the forest.</p>
    <p>How to make the trail: Start at the lake.</p><p>Interesting places: Forest and waterfall.</p>
    <p>Caution notes: Fog.</p><h2>Visitor guide</h2><p>Cookie banner</p></html>'''


def entry():
    return {"route_id": "PR-PNPE-2", "name": "Lake route", "url": "https://www.miteco.gob.es/route.html", "category": "PR"}


def test_discovery_ignores_duplicates_navigation_and_foreign_urls():
    parser = importlib.import_module("app.route_catalog.parser")
    rows = parser.discover_routes('''<a href="/one.html">PR-PNPE 2: Lake route</a>
      <a href="/one.html">PR-PNPE 2: Lake route</a><a href="/two.html">GR-PNPE 201: Long route</a>
      <a href="https://unrelated.invalid/a.html">PR-PNPE 9: Wrong source</a><a href="/map.pdf">Map</a>''',
      "https://www.miteco.gob.es/index.html")
    assert [row["route_id"] for row in rows] == ["PR-PNPE-2", "GR-PNPE-201"]


def test_loop_variants_retain_paired_values_and_full_text():
    parser = importlib.import_module("app.route_catalog.parser")
    route = parser.parse_route(page(), entry())
    variants = {v.key: v for v in route.variants}
    assert (variants["long"].distance_m, variants["long"].duration_minutes) == (5000, 150)
    assert (variants["short"].distance_m, variants["short"].duration_minutes) == (3000, 60)
    assert variants["long"].ascent_m == 50
    assert "waterfall" in route.description
    assert route.cautions == "Fog."
    assert "Cookie banner" not in route.description


def test_ambiguous_duration_is_unknown_instead_of_paired_by_position():
    parser = importlib.import_module("app.route_catalog.parser")
    route = parser.parse_route(page("21 km (linear)", "3 h 20 min. 5 h 30 min. (linear)"), entry())
    assert route.variants[0].duration_minutes is None
    assert route.warnings


def test_numeric_punctuation_and_hash_change_detection():
    parser = importlib.import_module("app.route_catalog.parser")
    models = importlib.import_module("app.route_catalog.models")
    route = parser.parse_route(page("4'3 km", "2 h 35 min"), entry())
    assert route.variants[0].distance_m == 4300
    assert route.variants[0].duration_minutes == 155
    assert models.content_hash(route) == models.content_hash(parser.parse_route(page("4'3 km", "2 h 35 min") + " ", entry()))
    assert models.content_hash(route) != models.content_hash(parser.parse_route(page("4'4 km", "2 h 35 min"), entry()))


def test_variant_elevations_are_not_taken_from_another_starting_point():
    parser = importlib.import_module("app.route_catalog.parser")
    html = page("14.6 km (Cable to village); 5.8 km (Fountain to village)",
                "4 h 15 min (Cable to village); 2 h 10 min (Fountain to village)")
    html = html.replace("50 m ascent and descent", "1192 m descent (Cable to village) / 758 m descent (Fountain to village)")
    route = parser.parse_route(html, entry())
    assert [v.descent_m for v in route.variants] == [1192, 758]


def test_complete_circuit_duration_is_not_the_partial_segment_duration():
    from app.route_catalog.parser import parse_route
    route = parse_route(page('13.5 km (Tramo Angon - Carombo - Beza) / 22.8 km (Circuito completo Angon - Carombo - Beza - Angon)',
        '3 h (Tramo Angon - Carombo) / 5 h 15 min (Tramo Angon - Carombo - Beza) / 8 h 45 min (Completando el regreso por el GR-201)'), entry())
    assert [v.duration_minutes for v in route.variants] == [315, 525]
    route = parse_route(page('13.5 km (Tramo Angon - Carombo - Beza)',
        '5 h 15 min (Tramo Angon- Carombo - Beza)'), entry())
    assert route.variants[0].duration_minutes == 315


def test_multiple_unclassified_segments_require_label_matches():
    from app.route_catalog.parser import parse_route
    route = parse_route(page('11 km (Ponton - Soto de Sajambre) / 27.5 km (Ponton - Amieva)',
        '3 h 55 min (Ponton - Soto de Sajambre) / 9 h 10 min (ruta completa, desde puerto del Ponton hasta Amieva)'), entry())
    assert [v.duration_minutes for v in route.variants] == [235, 550]


def test_starting_point_prefix_without_separator_does_not_change_previous_variant():
    from app.route_catalog.parser import parse_route
    route = parse_route(page('Partiendo de Buferrera: 10.2 km (ida) / 20.4 km (ida y vuelta) / Partiendo de Pandecarmen: 7.7 km (ida) / 15.4 km (ida y vuelta)',
        'Partiendo de Buferrera: 3 h 40 min (ida) / 6 h 30 min (ida y vuelta) Partiendo de Pandecarmen: 2 h 50 min (ida) / 5 h 40 min (ida y vuelta)'), entry())
    assert [v.duration_minutes for v in route.variants] == [220, 390, 170, 340]


def test_return_height_is_not_applied_to_outbound_and_ambiguous_direction_is_unknown():
    from app.route_catalog.parser import parse_route
    html = page('8.5 km (solo ida) / 17 km (ida y vuelta)', '5 h 45 min (tramo Poncebos - Cabrones)')
    route = parse_route(html.replace('50 m ascent and descent', '1.780 m subida (solo ida) + 1.780 m bajada (ida y vuelta)'), entry())
    assert [(v.ascent_m, v.descent_m) for v in route.variants] == [(1780, None), (1780, 1780)]
    html = page('15.1 km (solo ida) / 30.2 km (ida y vuelta)', '3 h 45 min ascenso + 3 h 15 min descenso (7 h recorrido completo)')
    route = parse_route(html.replace('50 m ascent and descent', '971 m (en ascenso o descenso, segun el sentido del recorrido)'), entry())
    assert route.variants[0].ascent_m is None and route.variants[0].descent_m is None
    assert route.variants[0].duration_minutes is None
    assert route.variants[1].duration_minutes == 420


def test_a_shared_starting_place_does_not_prove_the_same_segment():
    from app.route_catalog.parser import parse_route
    route = parse_route(page('8.3 km (Poncebos - Vega Urriellu) / 16.6 km (ida y vuelta)',
        '5 h 30 min (Poncebos - Camburero) / 10 h 30 min (ida y vuelta)'), entry())
    assert route.variants[0].duration_minutes is None
    assert route.variants[1].duration_minutes == 630


def test_partial_elevation_is_not_reused_as_complete_circuit_elevation():
    from app.route_catalog.parser import parse_route
    html = page('13.5 km (Tramo Angon - Carombo - Beza) / 22.8 km (Circuito completo Angon - Carombo - Beza - Angon)')
    route = parse_route(html.replace('50 m ascent and descent',
        '64 m descenso y 573 m subida (Tramo Angon - Carombo - Beza) / Se anaden 509 de descenso en el circuito completo'), entry())
    assert (route.variants[0].ascent_m, route.variants[0].descent_m) == (573, 64)
    assert (route.variants[1].ascent_m, route.variants[1].descent_m) == (None, None)


def test_return_descent_does_not_contaminate_a_named_one_way_segment():
    from app.route_catalog.parser import parse_route
    html = page('5.8 km (trayecto Urdon - Tresviso) / 11.6 km (ida y vuelta)')
    route = parse_route(html.replace('50 m ascent and descent', '825 m subida / (+ 825 m bajada en el regreso)'), entry())
    assert (route.variants[0].ascent_m, route.variants[0].descent_m) == (825, None)


def test_single_measurements_with_conflicting_directions_are_not_paired():
    from app.route_catalog.parser import parse_route
    route = parse_route(page('8 km (one-way)', '6 h (return trip)'), entry())
    assert route.variants[0].duration_minutes is None


def test_reversed_stage_duration_and_other_endpoint_elevation_are_unknown():
    from app.route_catalog.parser import parse_route
    route = parse_route(page('26.6 km (Etapa Poncebos - Covadonga)', '10 h 45 min (Etapa Covadonga - Poncebos)'), entry())
    assert route.variants[0].duration_minutes is None
    route = parse_route(page('8.3 km (Poncebos - Vega Urriellu)', '5 h 30 min (Poncebos - Camburero)'), entry())
    assert route.variants[0].duration_minutes is None
    html = page('8.3 km (Poncebos - Vega Urriellu) / 16.6 km (ida y vuelta)')
    route = parse_route(html.replace('50 m ascent and descent', '1.700 m ascenso Poncebos - Camburero / 1.700 m descenso en sentido inverso'), entry())
    assert [(v.ascent_m, v.descent_m) for v in route.variants] == [(None, None), (None, None)]


def test_unequal_one_way_gain_and_loss_are_not_copied_into_return_variant():
    from app.route_catalog.parser import parse_route
    html = page('13.2 km (recorrido de ida) / 26.4 km (ida y vuelta)')
    route = parse_route(html.replace('50 m ascent and descent', '831 m ascenso y 692 m descenso'), entry())
    assert (route.variants[0].ascent_m, route.variants[0].descent_m) == (831, 692)
    assert (route.variants[1].ascent_m, route.variants[1].descent_m) == (None, None)


def test_endpoint_matching_cannot_override_explicit_variant_kind():
    from app.route_catalog.parser import parse_route
    lengths = '10 km (Poncebos - Sotres solo ida); 20 km (Poncebos - Sotres ida y vuelta)'
    outward = parse_route(page(lengths, '3 h (Poncebos - Sotres solo ida)'), entry())
    assert [v.duration_minutes for v in outward.variants] == [180, None]
    returning = parse_route(page(lengths, '6 h (Poncebos - Sotres ida y vuelta)'), entry())
    assert [v.duration_minutes for v in returning.variants] == [None, 360]


def test_complete_route_elevation_cannot_establish_outbound_height():
    from app.route_catalog.parser import parse_route
    html = page('7.6 km (solo ida) / 15.2 km (ida y vuelta)')
    route = parse_route(html.replace('50 m ascent and descent', '610 m (ascenso y descenso para el recorrido completo)'), entry())
    assert [(v.ascent_m, v.descent_m) for v in route.variants] == [(None, None), (610, 610)]
