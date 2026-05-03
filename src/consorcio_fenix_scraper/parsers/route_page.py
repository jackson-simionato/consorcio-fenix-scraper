from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from urllib.parse import unquote, urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from consorcio_fenix_scraper.domain import FarePolicy, ItineraryStep, ParsedRoutePage, ScheduleEntry, ServiceDirection

TIME_RE = re.compile(r"\b(\d{1,2}:\d{2})\b")
FLAG_RE = re.compile(r"(?<!\w)([E*MR])(?!\w)")


def parse_route_page(html: str, page_url: str) -> ParsedRoutePage:
    soup = BeautifulSoup(html, "html.parser")
    code, name = _parse_title(soup, page_url)
    slug, _ = _route_identity_from_url(page_url)
    map_url = _extract_map_url(soup, page_url)
    service_directions = _parse_service_directions(soup)
    fare_region = _first_labeled_value(soup, "Tarifa")

    return ParsedRoutePage(
        code=code,
        name=name,
        slug=slug,
        page_url=page_url,
        map_url=map_url,
        category=_first_labeled_value(soup, "Característica", "Categoria"),
        fare_region=fare_region,
        fare_policy=_parse_fare_policy(soup, fare_region),
        last_changed=_parse_brazilian_date(_first_labeled_value(soup, "Alterada em", "Última alteração")),
        service_directions=service_directions,
        schedules=_parse_schedules(soup),
        itinerary_steps=_parse_itinerary(soup),
    )


def _parse_title(soup: BeautifulSoup, page_url: str) -> tuple[str, str]:
    slug, code = _route_identity_from_url(page_url)
    title = _text(soup.find("h1")) or _text(soup.find("title"))
    if title:
        separator_match = re.match(rf"\s*{re.escape(code)}\s*[-\u2013]\s*(.+?)\s*$", title, re.IGNORECASE)
        if separator_match:
            return code, separator_match.group(1)
    return code, slug.replace("-", " ").title()


def _route_identity_from_url(page_url: str) -> tuple[str, str]:
    path_tail = unquote(urlparse(page_url).path.rstrip("/").split("/")[-1])
    if "," not in path_tail:
        raise ValueError("Could not parse route code and name")
    slug, code = (part.strip() for part in path_tail.rsplit(",", 1))
    if not slug or not code:
        raise ValueError("Could not parse route code and name")
    return slug, code


def _extract_map_url(soup: BeautifulSoup, page_url: str) -> str | None:
    for iframe in soup.find_all("iframe"):
        src = iframe.get("src") or iframe.get("data-src")
        if src and ("/mapa/" in src or re.search(r"\.kml(?:$|\?)", src, re.IGNORECASE)):
            return urljoin(page_url, src)
    link = soup.find("a", href=re.compile(r"(/mapa/|\.kml(?:$|\?))", re.IGNORECASE))
    if isinstance(link, Tag) and link.get("href"):
        return urljoin(page_url, str(link["href"]))
    return None


def _find_labeled_value(soup: BeautifulSoup, label: str) -> str | None:
    pattern = re.compile(rf"{re.escape(label)}\s*(?::|-)\s*(.+)", re.IGNORECASE)
    for text in soup.stripped_strings:
        match = pattern.search(text)
        if match:
            return match.group(1).strip()
    for node in soup.find_all(string=re.compile(rf"^\s*{re.escape(label)}\s*:?\s*$", re.IGNORECASE)):
        parent = node.parent
        if not isinstance(parent, Tag):
            continue
        sibling = parent.find_next_sibling()
        while isinstance(sibling, Tag):
            value = _text(sibling)
            if value:
                return value
            sibling = sibling.find_next_sibling()
    return None


def _first_labeled_value(soup: BeautifulSoup, *labels: str) -> str | None:
    for label in labels:
        value = _find_labeled_value(soup, label)
        if value:
            return value
    return None


def _parse_fare_policy(soup: BeautifulSoup, region: str | None) -> FarePolicy | None:
    if not region:
        return None
    citizen_card_cents = _parse_fare(_first_labeled_value(soup, "Cartão Cidadão", "Cartao Cidadao"))
    vt_tourist_card_cents = _parse_fare(_first_labeled_value(soup, "Cartão VT/Turista", "Cartao VT/Turista"))
    cash_qrcode_pix_cents = _parse_fare(
        _first_labeled_value(
            soup,
            "Dinheiro/QRCODE/PIX",
            "Dinheiro/QRCODE",
            "Dinheiro/QRCode/PIX",
            "Dinheiro/QRCode",
        )
    )
    if citizen_card_cents is None or vt_tourist_card_cents is None or cash_qrcode_pix_cents is None:
        banner_fares = _parse_conventional_fare_banner(soup)
        citizen_card_cents = citizen_card_cents if citizen_card_cents is not None else banner_fares.get("citizen_card_cents")
        vt_tourist_card_cents = (
            vt_tourist_card_cents if vt_tourist_card_cents is not None else banner_fares.get("vt_tourist_card_cents")
        )
        cash_qrcode_pix_cents = (
            cash_qrcode_pix_cents if cash_qrcode_pix_cents is not None else banner_fares.get("cash_qrcode_pix_cents")
        )
    if citizen_card_cents is None and vt_tourist_card_cents is None and cash_qrcode_pix_cents is None:
        return None
    return FarePolicy(
        region=region,
        citizen_card_cents=citizen_card_cents,
        vt_tourist_card_cents=vt_tourist_card_cents,
        cash_qrcode_pix_cents=cash_qrcode_pix_cents,
    )


def _parse_conventional_fare_banner(soup: BeautifulSoup) -> dict[str, int]:
    fares: dict[str, int] = {}
    banner = _fare_banner_text(soup)
    if not banner:
        return fares
    conventional_text = re.split(r"\|\s*Tarifa\s+Executivo\b", banner, maxsplit=1, flags=re.IGNORECASE)[0]
    cash_match = re.search(r"Dinheiro\s*/\s*QRCODE\s*/\s*PIX\s*R\$\s*(\d+(?:[,.]\d{2})?)", conventional_text, re.IGNORECASE)
    citizen_match = re.search(r"\bCidad[aã]o\s*R\$\s*(\d+(?:[,.]\d{2})?)", conventional_text, re.IGNORECASE)
    vt_tourist_match = re.search(r"\bVT\.?\s*e\s*Turista\s*R\$\s*(\d+(?:[,.]\d{2})?)", conventional_text, re.IGNORECASE)
    if cash_match:
        fares["cash_qrcode_pix_cents"] = _parse_fare(cash_match.group(1)) or 0
    if citizen_match:
        fares["citizen_card_cents"] = _parse_fare(citizen_match.group(1)) or 0
    if vt_tourist_match:
        fares["vt_tourist_card_cents"] = _parse_fare(vt_tourist_match.group(1)) or 0
    return fares


def _fare_banner_text(soup: BeautifulSoup) -> str | None:
    banner = soup.find(id="tarifas")
    if isinstance(banner, Tag):
        return _text(banner)
    for text in soup.stripped_strings:
        if re.search(r"Tarifa\s+Convencional", text, re.IGNORECASE):
            return text.strip()
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
    schedules.extend(_parse_schedule_cards(soup))
    root = soup.find(id=re.compile("horario", re.IGNORECASE)) or soup
    for table in root.find_all("table"):
        day_type = _table_day_type(table)
        if not day_type:
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


def _parse_service_directions(soup: BeautifulSoup) -> list[ServiceDirection]:
    directions_by_label: dict[str, ServiceDirection] = {}
    for sequence, tab in enumerate(soup.find_all(class_=re.compile(r"\bmy-subtab-content\b")), start=1):
        if not isinstance(tab, Tag):
            continue
        heading = tab.find(re.compile("^h[1-6]$"))
        label = _text(heading)
        if not label:
            continue
        schedules = _parse_schedule_cards_in_group(tab, label)
        if not schedules:
            continue
        direction = directions_by_label.get(label)
        if direction is None:
            directions_by_label[label] = ServiceDirection(
                sequence=sequence,
                departure_label=label,
                schedules=schedules,
            )
            continue
        direction.schedules.extend(
            entry for entry in schedules if _schedule_key(entry) not in {_schedule_key(existing) for existing in direction.schedules}
        )
    if directions_by_label:
        return sorted(directions_by_label.values(), key=lambda direction: direction.sequence)
    return _parse_table_service_directions(soup)


def _parse_table_service_directions(soup: BeautifulSoup) -> list[ServiceDirection]:
    grouped: dict[str, list[ScheduleEntry]] = {}
    order: list[str] = []
    root = soup.find(id=re.compile("horario", re.IGNORECASE)) or soup
    for table in root.find_all("table"):
        day_type = _table_day_type(table)
        if not day_type:
            continue
        headers = [_text(cell) for cell in table.find_all("th")]
        if not headers:
            continue
        for row in table.find_all("tr"):
            cells = row.find_all("td")
            for index, cell in enumerate(cells):
                label = headers[index] if index < len(headers) else headers[-1]
                if label not in grouped:
                    grouped[label] = []
                    order.append(label)
                entries = _parse_schedule_cell(day_type, label, _text(cell))
                for entry in entries:
                    if _schedule_key(entry) not in {_schedule_key(existing) for existing in grouped[label]}:
                        grouped[label].append(entry)
    return [
        ServiceDirection(sequence=index, departure_label=label, schedules=grouped[label])
        for index, label in enumerate(order, start=1)
        if grouped[label]
    ]


def _parse_schedule_cards(soup: BeautifulSoup) -> list[ScheduleEntry]:
    schedules: list[ScheduleEntry] = []
    seen: set[tuple[str, str, str, tuple[str, ...]]] = set()
    for node in soup.find_all(attrs={"data-semana": True, "data-horario": True}):
        if not isinstance(node, Tag):
            continue
        day_type = str(node["data-semana"]).strip()
        time = str(node["data-horario"]).strip()
        if not day_type or not TIME_RE.fullmatch(time):
            continue
        label = _schedule_card_label(node)
        entry = ScheduleEntry(
            day_type=day_type,
            departure_label=label,
            time=time.zfill(5),
            flags=tuple(FLAG_RE.findall(_text(node))),
        )
        key = _schedule_key(entry)
        if key not in seen:
            seen.add(key)
            schedules.append(entry)
    return schedules


def _parse_schedule_cards_in_group(group: Tag, label: str) -> list[ScheduleEntry]:
    schedules: list[ScheduleEntry] = []
    seen: set[tuple[str, str, str, tuple[str, ...]]] = set()
    for node in group.find_all(attrs={"data-semana": True, "data-horario": True}):
        if not isinstance(node, Tag):
            continue
        day_type = str(node["data-semana"]).strip()
        time = str(node["data-horario"]).strip()
        if not day_type or not TIME_RE.fullmatch(time):
            continue
        entry = ScheduleEntry(
            day_type=day_type,
            departure_label=label,
            time=time.zfill(5),
            flags=tuple(FLAG_RE.findall(_text(node))),
        )
        key = _schedule_key(entry)
        if key not in seen:
            seen.add(key)
            schedules.append(entry)
    return schedules


def _schedule_key(entry: ScheduleEntry) -> tuple[str, str, str, tuple[str, ...]]:
    return entry.day_type, entry.departure_label, entry.time, entry.flags


def _schedule_card_label(node: Tag) -> str:
    tab = node.find_parent(class_=re.compile(r"\bmy-subtab-content\b"))
    if isinstance(tab, Tag):
        heading = tab.find(re.compile("^h[1-6]$"))
        label = _text(heading)
        if label:
            return label
    return ""


def _table_day_type(table: Tag) -> str:
    caption = table.find("caption")
    caption_text = _text(caption)
    if caption_text:
        return caption_text
    heading = table.find_previous(re.compile("^h[1-6]$"))
    return _text(heading)


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
    root = soup.find(class_=re.compile(r"\bcontent-text-itinerario\b")) or soup.find(id=re.compile("itiner", re.IGNORECASE))
    if not isinstance(root, Tag):
        heading = soup.find(string=re.compile("Itiner", re.IGNORECASE))
        root = heading.find_parent().find_next_sibling() if heading and heading.find_parent() else None
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
