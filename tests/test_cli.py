import logging
import asyncio
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from typer.testing import CliRunner

from consorcio_fenix_scraper import cli
from consorcio_fenix_scraper.cli import app
from consorcio_fenix_scraper.db import (
    Base,
    RouteDirectionRecord,
    RouteSegmentRecord,
    ScrapeRunRecord,
    _prepare_snapshot,
    _persist_data_batch,
)
from consorcio_fenix_scraper.domain import ParsedRoutePage, RouteDirection, RouteSnapshot


def test_dry_run_cli_parses_fixture_pages_without_database_writes():
    runner = CliRunner()
    fixture_dir = Path(__file__).parent / "fixtures"

    result = runner.invoke(
        app,
        [
            "scrape-routes",
            "--dry-run",
            "--route-html",
            str(fixture_dir / "route_page.html"),
            "--map-html",
            str(fixture_dir / "map_page.html"),
        ],
    )

    assert result.exit_code == 0
    assert "routes=1" in result.output
    assert "schedules=5" in result.output
    assert "geometries=2" in result.output
    assert "itinerary_steps=3" in result.output


def test_dry_run_cli_emits_lifecycle_logs_without_changing_summary(monkeypatch, caplog):
    runner = CliRunner()
    fixture_dir = Path(__file__).parent / "fixtures"
    monkeypatch.delenv("LOG_LEVEL", raising=False)

    with caplog.at_level(logging.DEBUG, logger="consorcio_fenix_scraper"):
        result = runner.invoke(
            app,
            [
                "scrape-routes",
                "--dry-run",
                "--route-html",
                str(fixture_dir / "route_page.html"),
                "--map-html",
                str(fixture_dir / "map_page.html"),
            ],
        )

    assert result.exit_code == 0
    assert result.stdout.strip() == "routes=1 schedules=5 geometries=2 itinerary_steps=3 stops=0 warnings=1 failures=0"
    assert "Starting route scrape" in caplog.text
    assert "Running in dry-run mode; database writes disabled" in caplog.text
    assert (
        "Parsed fixture route code=110 schedules=5 service_directions=2 directions=2 direction_matches=2"
        in caplog.text
    )
    assert "fetch_complete routes=1 duration_seconds=" in caplog.text
    assert "routes_per_second=" in caplog.text
    assert "Completed route scrape: routes=1 schedules=5 geometries=2 itinerary_steps=3 stops=0 warnings=1 failures=0" in caplog.text


def test_database_batch_rows_override_reaches_persistence_without_changing_stdout(monkeypatch):
    runner = CliRunner()
    fixture_dir = Path(__file__).parent / "fixtures"
    captured: dict[str, int] = {}

    def fake_persist(_session_factory, _source_url, snapshots, *, max_batch_rows):
        captured["max_batch_rows"] = max_batch_rows
        return cli._summarize_snapshots(snapshots)

    monkeypatch.setattr(cli, "make_session_factory", lambda _url: object())
    monkeypatch.setattr(cli, "persist_snapshots", fake_persist)

    result = runner.invoke(
        app,
        [
            "scrape-routes",
            "--database-url",
            "sqlite://",
            "--db-batch-rows",
            "1234",
            "--route-html",
            str(fixture_dir / "route_page.html"),
            "--map-html",
            str(fixture_dir / "map_page.html"),
        ],
    )

    assert result.exit_code == 0
    assert captured == {"max_batch_rows": 1234}
    assert result.stdout.strip() == "routes=1 schedules=5 geometries=2 itinerary_steps=3 stops=0 warnings=1 failures=0"


def test_live_snapshot_fetching_respects_concurrency_and_preserves_route_order(monkeypatch):
    route_a = """
    <html><body>
      <h1>100 - Route A</h1>
      <iframe data-src="/mapa/route-a,100"></iframe>
      <div class="my-subtab-content"><h5>Saída A</h5><div data-semana="Dias Úteis" data-horario="06:00"><a>06:00</a></div></div>
    </body></html>
    """
    route_b = """
    <html><body>
      <h1>200 - Route B</h1>
      <iframe data-src="/mapa/route-b,200"></iframe>
      <div class="my-subtab-content"><h5>Saída B</h5><div data-semana="Dias Úteis" data-horario="07:00"><a>07:00</a></div></div>
    </body></html>
    """
    kml = """<?xml version="1.0" encoding="UTF-8"?>
    <kml xmlns="http://www.opengis.net/kml/2.2">
      <Document>
        <Placemark><name>Ida</name><LineString><coordinates>-48.1,-27.1,0 -48.2,-27.2,0</coordinates></LineString></Placemark>
      </Document>
    </kml>
    """
    pages = {
        "https://example.test/horarios": """
        <a href="/horarios/route-a,100">A</a>
        <a href="/horarios/route-b,200">B</a>
        """,
        "https://example.test/horarios/route-a,100": route_a,
        "https://example.test/horarios/route-b,200": route_b,
        "https://example.test/mapa/route-a,100": kml,
        "https://example.test/mapa/route-b,200": kml,
    }
    active_routes = 0
    max_active_routes = 0

    class FakeFetcher:
        async def get_text(self, url: str) -> str:
            nonlocal active_routes, max_active_routes
            if "/horarios/route-" in url:
                active_routes += 1
                max_active_routes = max(max_active_routes, active_routes)
                await asyncio.sleep(0.01 if url.endswith("route-a,100") else 0)
                active_routes -= 1
            return pages[url]

        async def close(self) -> None:
            return None

    monkeypatch.setattr(cli, "AsyncHttpFetcher", lambda: FakeFetcher())

    snapshots = asyncio.run(cli._fetch_live_snapshots_async("https://example.test/horarios", limit=None, concurrency=2))

    assert max_active_routes == 2
    assert [snapshot.route.code for snapshot in snapshots] == ["100", "200"]


def test_live_snapshot_fetching_honors_concurrency_limit(monkeypatch):
    route_html = """
    <html><body>
      <h1>100 - Route A</h1>
      <iframe data-src="/mapa/route-a,100"></iframe>
      <div class="my-subtab-content"><h5>Saída A</h5><div data-semana="Dias Úteis" data-horario="06:00"><a>06:00</a></div></div>
    </body></html>
    """
    kml = """<?xml version="1.0" encoding="UTF-8"?>
    <kml xmlns="http://www.opengis.net/kml/2.2">
      <Document>
        <Placemark><name>Ida</name><LineString><coordinates>-48.1,-27.1,0 -48.2,-27.2,0</coordinates></LineString></Placemark>
      </Document>
    </kml>
    """
    pages = {
        "https://example.test/horarios": """
        <a href="/horarios/route-a,100">A</a>
        <a href="/horarios/route-b,200">B</a>
        """,
        "https://example.test/horarios/route-a,100": route_html,
        "https://example.test/horarios/route-b,200": route_html.replace("100", "200"),
        "https://example.test/mapa/route-a,100": kml,
        "https://example.test/mapa/route-a,200": kml,
    }
    active_routes = 0
    max_active_routes = 0

    class FakeFetcher:
        async def get_text(self, url: str) -> str:
            nonlocal active_routes, max_active_routes
            if "/horarios/route-" in url:
                active_routes += 1
                max_active_routes = max(max_active_routes, active_routes)
                await asyncio.sleep(0)
                active_routes -= 1
            return pages[url]

        async def close(self) -> None:
            return None

    monkeypatch.setattr(cli, "AsyncHttpFetcher", lambda: FakeFetcher())

    asyncio.run(cli._fetch_live_snapshots_async("https://example.test/horarios", limit=None, concurrency=1))

    assert max_active_routes == 1


def test_live_snapshot_fetching_rejects_non_positive_concurrency():
    try:
        asyncio.run(cli._fetch_live_snapshots_async("https://example.test/horarios", limit=None, concurrency=0))
    except ValueError as exc:
        assert str(exc) == "concurrency must be greater than zero"
    else:
        raise AssertionError("expected ValueError")


def test_live_cli_rejects_zero_concurrency_before_fetching():
    runner = CliRunner()

    result = runner.invoke(app, ["scrape-routes", "--dry-run", "--source-url", "https://example.test/horarios", "--concurrency", "0"])

    assert result.exit_code != 0
    assert isinstance(result.exception, ValueError)
    assert str(result.exception) == "concurrency must be greater than zero"


def test_rebuild_route_segments_cli_rebuilds_from_stored_route_directions(tmp_path):
    runner = CliRunner()
    database_url = _sqlite_database_url(tmp_path)
    session_factory = _prepared_session_factory(database_url)
    with session_factory.begin() as session:
        run = ScrapeRunRecord(source_url="https://example.test/horarios")
        session.add(run)
        session.flush()
        _persist_data_batch(session, run.id, [_prepare_snapshot(_snapshot_with_direction())])
        session.query(RouteSegmentRecord).delete()

    result = runner.invoke(app, ["rebuild-route-segments", "--database-url", database_url])

    assert result.exit_code == 0
    assert result.stdout.strip() == "route_directions=1 segments_written=5"
    with session_factory() as session:
        direction = session.query(RouteDirectionRecord).one()
        segments = session.query(RouteSegmentRecord).order_by(RouteSegmentRecord.sequence).all()

    assert len(segments) == 5
    assert {segment.route_direction_id for segment in segments} == {direction.id}
    assert segments[0].geometry.startswith("SRID=4326;LINESTRING(-48.0 -27.0, ")
    assert segments[-1].geometry.endswith("-48.0 -27.01)")


def test_rebuild_route_segments_cli_is_idempotent_and_does_not_rescrape(tmp_path, monkeypatch):
    runner = CliRunner()
    database_url = _sqlite_database_url(tmp_path)
    session_factory = _prepared_session_factory(database_url)
    with session_factory.begin() as session:
        run = ScrapeRunRecord(source_url="https://example.test/horarios")
        session.add(run)
        session.flush()
        _persist_data_batch(session, run.id, [_prepare_snapshot(_snapshot_with_direction())])

    async def fail_fetch(*_args, **_kwargs):
        raise AssertionError("rebuild must not fetch route pages")

    monkeypatch.setattr(cli, "_fetch_live_snapshots_async", fail_fetch)

    first = runner.invoke(app, ["rebuild-route-segments", "--database-url", database_url])
    second = runner.invoke(app, ["rebuild-route-segments", "--database-url", database_url])

    assert first.exit_code == 0
    assert second.exit_code == 0
    assert first.stdout == second.stdout
    with session_factory() as session:
        assert session.query(ScrapeRunRecord).count() == 1
        assert session.query(RouteSegmentRecord).count() == 5


def _sqlite_database_url(tmp_path: Path) -> str:
    return f"sqlite:///{tmp_path / 'routes.db'}"


def _prepared_session_factory(database_url: str):
    engine = create_engine(database_url, future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)


def _snapshot_with_direction() -> RouteSnapshot:
    return RouteSnapshot(
        route=ParsedRoutePage(
            code="110",
            name="TICEN - TITRI",
            slug="ticen-titri",
            page_url="https://example.test/horarios/ticen-titri,110",
            map_url="https://example.test/mapa/110",
        ),
        directions=[
            RouteDirection(
                name="Ida",
                coordinates=[
                    (-48.0, -27.0),
                    (-48.0, -27.01),
                ],
            ),
        ],
        source_hash="source-a",
        map_hash="map-a",
    )
