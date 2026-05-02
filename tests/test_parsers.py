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


def test_route_page_parser_keeps_hyphenated_route_codes_from_url():
    html = "<html><body><h1>V-844 - Bairro de Fatima</h1></body></html>"

    route = parse_route_page(
        html,
        page_url="https://www.consorciofenix.com.br/horarios/bairro-de-fatima,V-844",
    )

    assert route.code == "V-844"
    assert route.name == "Bairro de Fatima"
    assert route.slug == "bairro-de-fatima"


def test_route_page_parser_falls_back_to_slug_name_for_arbitrary_codes():
    route = parse_route_page(
        "<html><body></body></html>",
        page_url="https://www.consorciofenix.com.br/horarios/titri-ticen-via-gama-deca-hi,132A.1",
    )

    assert route.code == "132A.1"
    assert route.name == "Titri Ticen Via Gama Deca Hi"
    assert route.slug == "titri-ticen-via-gama-deca-hi"


def test_route_page_parser_handles_split_labels_captioned_schedules_and_kml_link():
    html = """
    <html><body>
      <h1>110 - TICEN - TITRI via Mauro Ramos</h1>
      <dl>
        <dt>Tarifa</dt><dd>R$ 6,90</dd>
        <dt>Categoria</dt><dd>Convencional</dd>
      </dl>
      <a href="/arquivos/kml/ticen-titri-via-mauro-ramos,110.kml">Itinerário KML</a>
      <section id="horarios">
        <table>
          <caption>Dias Úteis</caption>
          <thead><tr><th>TICEN</th><th>TITRI</th></tr></thead>
          <tbody><tr><td>06:00 E</td><td>06:30 *</td></tr></tbody>
        </table>
      </section>
    </body></html>
    """

    route = parse_route_page(
        html,
        page_url="https://www.consorciofenix.com.br/horarios/ticen-titri-via-mauro-ramos,110",
    )

    assert route.category == "Convencional"
    assert route.fare_cents == 690
    assert route.map_url == "https://www.consorciofenix.com.br/arquivos/kml/ticen-titri-via-mauro-ramos,110.kml"
    assert [(entry.day_type, entry.departure_label, entry.time, entry.flags) for entry in route.schedules] == [
        ("Dias Úteis", "TICEN", "06:00", ("E",)),
        ("Dias Úteis", "TITRI", "06:30", ("*",)),
    ]


def test_route_page_parser_handles_live_schedule_cards_data_src_map_and_itinerary_list():
    html = """
    <html><body>
      <h1>665 - Abraão</h1>
      <div class="content-horarios-int">
        <div class="my-subtab-content">
          <h5>Saída Abraão</h5>
          <div class="row row-horarios">
            <div data-semana="Dias Úteis" data-horario="05:30">
              <a>05:30 <b>E M</b></a>
            </div>
          </div>
        </div>
        <div class="my-subtab-content">
          <h5>Saída TICEN - Plataforma B - Box 9</h5>
          <div class="row row-horarios">
            <div data-semana="Sábado" data-horario="00:15">
              <a>00:15 <b>E R</b></a>
            </div>
          </div>
        </div>
      </div>
      <div class="content-text-itinerario">
        <ol>
          <li>TICEN - TERMINAL DE INTEGRAÇÃO DO CENTRO</li>
          <li>RUA PEDRO BITTENCOURT</li>
        </ol>
      </div>
      <iframe data-src="/mapa/abraao,665"></iframe>
    </body></html>
    """

    route = parse_route_page(html, page_url="https://www.consorciofenix.com.br/horarios/abraao,665")

    assert route.map_url == "https://www.consorciofenix.com.br/mapa/abraao,665"
    assert [step.name for step in route.itinerary_steps] == [
        "TICEN - TERMINAL DE INTEGRAÇÃO DO CENTRO",
        "RUA PEDRO BITTENCOURT",
    ]
    assert [(direction.sequence, direction.departure_label) for direction in route.service_directions] == [
        (1, "Saída Abraão"),
        (2, "Saída TICEN - Plataforma B - Box 9"),
    ]
    assert [
        (entry.day_type, entry.departure_label, entry.time, entry.flags)
        for entry in route.service_directions[0].schedules
    ] == [
        ("Dias Úteis", "Saída Abraão", "05:30", ("E", "M")),
    ]
    assert [
        (entry.day_type, entry.departure_label, entry.time, entry.flags)
        for entry in route.service_directions[1].schedules
    ] == [
        ("Sábado", "Saída TICEN - Plataforma B - Box 9", "00:15", ("E", "R")),
    ]
    assert [(entry.day_type, entry.departure_label, entry.time, entry.flags) for entry in route.schedules] == [
        ("Dias Úteis", "Saída Abraão", "05:30", ("E", "M")),
        ("Sábado", "Saída TICEN - Plataforma B - Box 9", "00:15", ("E", "R")),
    ]


def test_kml_parser_extracts_linestrings_with_lon_lat_order():
    html = (FIXTURES / "map_page.html").read_text()

    kml = extract_kml(html)
    directions = parse_kml_directions(kml)

    assert [direction.name for direction in directions] == ["Ida", "Volta"]
    assert directions[0].coordinates == [(-48.5480, -27.5969), (-48.5440, -27.5900)]


def test_kml_parser_accepts_raw_kml_file_contents():
    kml = """<?xml version="1.0" encoding="UTF-8"?>
    <kml xmlns="http://www.opengis.net/kml/2.2">
      <Document>
        <Placemark><name>Ida</name><LineString><coordinates>-48.1,-27.1,0 -48.2,-27.2,0</coordinates></LineString></Placemark>
      </Document>
    </kml>
    """

    directions = parse_kml_directions(extract_kml(kml))

    assert directions[0].coordinates == [(-48.1, -27.1), (-48.2, -27.2)]


def test_kml_extractor_unescapes_javascript_escaped_forward_slashes():
    html = r'''<script>
    var kmltext = "<?xml version=\"1.0\"?><kml xmlns=\"http:\/\/www.opengis.net\/kml\/2.2\"><Document><name>665.kml<\/name></Document><\/kml>";
    </script>'''

    kml = extract_kml(html)

    assert "<name>665.kml</name>" in kml
    assert kml.endswith("</kml>")
