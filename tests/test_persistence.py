from consorcio_fenix_scraper.db import _linestring_wkt
from consorcio_fenix_scraper.domain import RouteDirection


def test_linestring_wkt_uses_srid_4326_and_lon_lat_order():
    direction = RouteDirection(name="Ida", coordinates=[(-48.548, -27.5969), (-48.544, -27.59)])

    assert _linestring_wkt(direction) == "SRID=4326;LINESTRING(-48.548 -27.5969, -48.544 -27.59)"
