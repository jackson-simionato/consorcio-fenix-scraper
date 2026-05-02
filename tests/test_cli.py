from pathlib import Path

from typer.testing import CliRunner

from consorcio_fenix_scraper.cli import app


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
