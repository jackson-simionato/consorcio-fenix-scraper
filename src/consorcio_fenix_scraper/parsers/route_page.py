from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from consorcio_fenix_scraper.domain import ItineraryStep, ParsedRoutePage, ScheduleEntry

TIME_RE = re.compile(r"\b(\d{1,2}:\d{2})\b")
FLAG_RE = re.compile(r"(?<!\w)([E*MR])(?!\w)")


def parse_route_page(html: str, page_url: str) -> ParsedRoutePage:
    soup = BeautifulSoup(html, "html.parser")
    code, name = _parse_title(soup, page_url)
    slug = _slug_from_url(page_url)
    map_url = _extract_map_url(soup, page_url)

    return ParsedRoutePage(
        code=code,
        name=name,
        slug=slug,
        page_url=page_url,
        map_url=map_url,
        category=_find_labeled_value(soup, "Categoria"),
        fare_cents=_parse_fare(_find_labeled_value(soup, "Tarifa")),
        last_changed=_parse_brazilian_date(_find_labeled_value(soup, "Última alteração")),
        schedules=_parse_schedules(soup),
        itinerary_steps=_parse_itinerary(soup),
    )


def _parse_title(soup: BeautifulSoup, page_url: str) -> tuple[str, str]:
    title = _text(soup.find("h1")) or _text(soup.find("title"))
    if title:
        match = re.match(r"\s*([A-Za-z0-9.]+)\s*[-–]\s*(.+?)\s*$", title)
        if match:
            return match.group(1), match.group(2)

    path_tail = urlparse(page_url).path.rstrip("/").split("/")[-1]
    if "," in path_tail:
        slug, code = path_tail.rsplit(",", 1)
        return code, slug.replace("-", " ").title()
    raise ValueError("Could not parse route code and name")


def _slug_from_url(page_url: str) -> str:
    path_tail = urlparse(page_url).path.rstrip("/").split("/")[-1]
    return path_tail.rsplit(",", 1)[0] if "," in path_tail else path_tail


def _extract_map_url(soup: BeautifulSoup, page_url: str) -> str | None:
    for iframe in soup.find_all("iframe"):
        src = iframe.get("src")
        if src and "/mapa/" in src:
            return urljoin(page_url, src)
    link = soup.find("a", href=re.compile(r"/mapa/"))
    if isinstance(link, Tag) and link.get("href"):
        return urljoin(page_url, str(link["href"]))
    return None


def _find_labeled_value(soup: BeautifulSoup, label: str) -> str | None:
    pattern = re.compile(rf"{re.escape(label)}\s*:\s*(.+)", re.IGNORECASE)
    for text in soup.stripped_strings:
        match = pattern.search(text)
        if match:
            return match.group(1).strip()
    return None


def _parse_fare(value: str | None) -> int | None:
    if not value:
        return None
    match = re.search(r"(\d+(?:[,.]\d{2})?)", value)
    if not match:
        return None
    decimal = Decimal(match.group(1).replace(",", "."))
    return int(decimal * 100)


def _parse_brazilian_date(value: str | None) -> date | None:
    if not value:
        return None
    match = re.search(r"(\d{2})/(\d{2})/(\d{4})", value)
    if not match:
        return None
    day, month, year = (int(part) for part in match.groups())
    return date(year, month, day)


def _parse_schedules(soup: BeautifulSoup) -> list[ScheduleEntry]:
    schedules: list[ScheduleEntry] = []
    root = soup.find(id=re.compile("horario", re.IGNORECASE)) or soup
    for heading in root.find_all(re.compile("^h[1-6]$")):
        day_type = _text(heading)
        if not day_type:
            continue
        table = heading.find_next("table")
        if not isinstance(table, Tag):
            continue
        headers = [_text(cell) for cell in table.find_all("th")]
        if not headers:
            continue
        for row in table.find_all("tr"):
            cells = row.find_all("td")
            for index, cell in enumerate(cells):
                label = headers[index] if index < len(headers) else headers[-1]
                schedules.extend(_parse_schedule_cell(day_type, label, _text(cell)))
    return schedules


def _parse_schedule_cell(day_type: str, label: str, value: str) -> list[ScheduleEntry]:
    entries: list[ScheduleEntry] = []
    for time_match in TIME_RE.finditer(value):
        token_end = _next_time_start(value, time_match.end())
        token = value[time_match.start() : token_end]
        entries.append(
            ScheduleEntry(
                day_type=day_type,
                departure_label=label,
                time=time_match.group(1).zfill(5),
                flags=tuple(FLAG_RE.findall(token)),
            )
        )
    return entries


def _next_time_start(value: str, start: int) -> int:
    match = TIME_RE.search(value, start)
    return match.start() if match else len(value)


def _parse_itinerary(soup: BeautifulSoup) -> list[ItineraryStep]:
    root = soup.find(id=re.compile("itiner", re.IGNORECASE))
    if not isinstance(root, Tag):
        heading = soup.find(string=re.compile("Itiner", re.IGNORECASE))
        root = heading.find_parent() if heading else None
    if not isinstance(root, Tag):
        return []

    items = root.find_all("li")
    if not items:
        items = root.find_all(["p", "span"])
    return [
        ItineraryStep(sequence=index, name=_text(item))
        for index, item in enumerate(items, start=1)
        if _text(item)
    ]


def _text(node: Tag | object | None) -> str:
    if not isinstance(node, Tag):
        return ""
    return " ".join(node.get_text(" ", strip=True).split())
