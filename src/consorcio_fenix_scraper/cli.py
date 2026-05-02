from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from consorcio_fenix_scraper.db import hash_text, make_session_factory, persist_snapshots
from consorcio_fenix_scraper.domain import RouteSnapshot, ScrapeRunResult
from consorcio_fenix_scraper.http import BASE_URL, HttpFetcher, limited, parse_route_links
from consorcio_fenix_scraper.logging import configure_logging, get_logger
from consorcio_fenix_scraper.parsers.kml import extract_kml, parse_kml_directions
from consorcio_fenix_scraper.parsers.route_page import parse_route_page
from consorcio_fenix_scraper.stops import FloripaNoPontoStopAdapter

app = typer.Typer(no_args_is_help=True)
logger = get_logger(__name__)


@app.callback()
def main() -> None:
    """Consórcio Fênix batch scraping commands."""


@app.command()
def scrape_routes(
    database_url: Annotated[str | None, typer.Option(envvar="DATABASE_URL")] = None,
    dry_run: Annotated[bool, typer.Option(help="Parse and report counts without database writes.")] = False,
    limit: Annotated[int | None, typer.Option(help="Limit route count for smoke runs.")] = None,
    source_url: Annotated[str, typer.Option(help="Route index URL to discover /horarios links.")] = f"{BASE_URL}/horarios",
    route_html: Annotated[
        Path | None,
        typer.Option(help="Local route HTML fixture. When set, live fetching is skipped."),
    ] = None,
    map_html: Annotated[
        Path | None,
        typer.Option(help="Local map iframe HTML fixture used with --route-html."),
    ] = None,
) -> None:
    configure_logging()
    logger.info("Starting route scrape")
    logger.info("Source URL: %s", source_url)
    if limit is not None:
        logger.info("Route limit: %s", limit)
    if dry_run:
        logger.info("Running in dry-run mode; database writes disabled")
    else:
        logger.info("Running in database write mode")

    snapshots = _load_fixture_snapshots(route_html, map_html) if route_html else _fetch_live_snapshots(source_url, limit)
    result = _summarize_snapshots(snapshots)

    stop_result = FloripaNoPontoStopAdapter().discover()
    if stop_result.status != "success":
        result.warnings.append(f"stop_adapter={stop_result.status}: {stop_result.message}")

    if not dry_run:
        if not database_url:
            raise typer.BadParameter("--database-url or DATABASE_URL is required unless --dry-run is set")
        session_factory = make_session_factory(database_url)
        with session_factory.begin() as session:
            result = persist_snapshots(session, source_url, snapshots)
            if stop_result.status != "success":
                result.warnings.append(f"stop_adapter={stop_result.status}: {stop_result.message}")

    logger.info("Completed route scrape: %s", _format_result(result))
    typer.echo(_format_result(result))


def _load_fixture_snapshots(route_html: Path | None, map_html: Path | None) -> list[RouteSnapshot]:
    if route_html is None:
        return []
    logger.info("Loading route fixture: %s", route_html)
    route_text = route_html.read_text()
    page_url = "https://www.consorciofenix.com.br/horarios/ticen-titri-via-mauro-ramos,110"
    route = parse_route_page(route_text, page_url=page_url)
    map_text = map_html.read_text() if map_html else ""
    if map_html:
        logger.info("Loading map fixture: %s", map_html)
    directions = parse_kml_directions(extract_kml(map_text)) if map_text else []
    source_hash = hash_text(route_text)
    map_hash = hash_text(map_text) if map_text else None
    logger.debug(
        "Parsed fixture route code=%s schedules=%s directions=%s source_hash=%s map_hash=%s",
        route.code,
        len(route.schedules),
        len(directions),
        source_hash,
        map_hash,
    )
    return [RouteSnapshot(route=route, directions=directions, source_hash=source_hash, map_hash=map_hash)]


def _fetch_live_snapshots(source_url: str, limit: int | None) -> list[RouteSnapshot]:
    fetcher = HttpFetcher()
    try:
        logger.info("Fetching route index: %s", source_url)
        index_html = fetcher.get_text(source_url)
        route_urls = limited(parse_route_links(index_html), limit)
        logger.info("Discovered %s route links", len(route_urls))
        snapshots: list[RouteSnapshot] = []
        for index, route_url in enumerate(route_urls, start=1):
            logger.info("Fetching route %s/%s: %s", index, len(route_urls), route_url)
            route_html = fetcher.get_text(route_url)
            route = parse_route_page(route_html, page_url=route_url)
            map_text = fetcher.get_text(route.map_url) if route.map_url else ""
            directions = parse_kml_directions(extract_kml(map_text)) if map_text else []
            logger.info(
                "Parsed route %s: schedules=%s directions=%s itinerary_steps=%s",
                route.code,
                len(route.schedules),
                len(directions),
                len(route.itinerary_steps),
            )
            logger.debug(
                "Route %s hashes: source_hash=%s map_hash=%s",
                route.code,
                hash_text(route_html),
                hash_text(map_text) if map_text else None,
            )
            snapshots.append(
                RouteSnapshot(
                    route=route,
                    directions=directions,
                    source_hash=hash_text(route_html),
                    map_hash=hash_text(map_text) if map_text else None,
                )
            )
        return snapshots
    finally:
        fetcher.close()


def _summarize_snapshots(snapshots: list[RouteSnapshot]) -> ScrapeRunResult:
    return ScrapeRunResult(
        routes=len(snapshots),
        schedules=sum(len(snapshot.route.schedules) for snapshot in snapshots),
        geometries=sum(len(snapshot.directions) for snapshot in snapshots),
        itinerary_steps=sum(len(snapshot.route.itinerary_steps) for snapshot in snapshots),
    )


def _format_result(result: ScrapeRunResult) -> str:
    fields = [
        f"routes={result.routes}",
        f"schedules={result.schedules}",
        f"geometries={result.geometries}",
        f"itinerary_steps={result.itinerary_steps}",
        f"stops={result.stops}",
        f"warnings={len(result.warnings)}",
        f"failures={len(result.failures)}",
    ]
    return " ".join(fields)
