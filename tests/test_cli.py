import logging
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


def test_dry_run_cli_emits_lifecycle_logs_without_changing_summary(monkeypatch, caplog):
    runner = CliRunner()
    fixture_dir = Path(__file__).parent / "fixtures"
    monkeypatch.delenv("LOG_LEVEL", raising=False)

    with caplog.at_level(logging.INFO, logger="consorcio_fenix_scraper"):
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
    assert "Completed route scrape: routes=1 schedules=5 geometries=2 itinerary_steps=3 stops=0 warnings=1 failures=0" in caplog.text
