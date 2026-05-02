from pathlib import Path

from consorcio_fenix_scraper.parsers.kml import extract_kml, parse_kml_directions
from consorcio_fenix_scraper.parsers.route_page import parse_route_page


FIXTURES = Path(__file__).parent / "fixtures"


def test_route_page_parser_extracts_metadata_schedules_flags_and_itinerary():
    html = (FIXTURES / "route_page.html").read_text()

    route = parse_route_page(
        html,
        page_url="https://www.consorciofenix.com.br/horarios/ticen-titri-via-mauro-ramos,110",
    )

    assert route.code == "110"
    assert route.name == "TICEN - TITRI via Mauro Ramos"
    assert route.slug == "ticen-titri-via-mauro-ramos"
    assert route.category == "Executivo"
    assert route.fare_cents == 690
    assert route.last_changed.isoformat() == "2026-04-01"
    assert route.map_url == "https://www.consorciofenix.com.br/mapa/ticen-titri-via-mauro-ramos,110"
    assert [step.name for step in route.itinerary_steps] == [
        "Terminal de Integração do Centro",
        "Avenida Mauro Ramos",
        "Terminal de Integração da Trindade",
    ]
    assert [(entry.day_type, entry.departure_label, entry.time, entry.flags) for entry in route.schedules] == [
        ("Dias Úteis", "TICEN", "06:00", ("E",)),
        ("Dias Úteis", "TITRI", "06:30", ("*",)),
        ("Dias Úteis", "TICEN", "07:00", ("M",)),
        ("Dias Úteis", "TITRI", "07:35", ("R",)),
        ("Sábado", "TICEN", "08:00", ()),
    ]


def test_kml_parser_extracts_linestrings_with_lon_lat_order():
    html = (FIXTURES / "map_page.html").read_text()

    kml = extract_kml(html)
    directions = parse_kml_directions(kml)

    assert [direction.name for direction in directions] == ["Ida", "Volta"]
    assert directions[0].coordinates == [(-48.5480, -27.5969), (-48.5440, -27.5900)]
