from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET

from consorcio_fenix_scraper.domain import RouteDirection

KML_TEXT_RE = re.compile(r"kmltext\s*=\s*(['\"])(?P<value>.*?)(?<!\\)\1", re.DOTALL)
KML_NS = {"kml": "http://www.opengis.net/kml/2.2"}


def extract_kml(map_html: str) -> str:
    stripped = map_html.strip()
    if stripped.startswith("<?xml") or stripped.startswith("<kml"):
        return stripped
    match = KML_TEXT_RE.search(map_html)
    if not match:
        raise ValueError("Could not find kmltext JavaScript assignment")
    value = match.group("value")
    decoded = bytes(value.replace("\\/", "/"), "utf-8").decode("unicode_escape")
    return html.unescape(decoded)


def parse_kml_directions(kml_text: str) -> list[RouteDirection]:
    root = ET.fromstring(kml_text)
    directions: list[RouteDirection] = []
    for placemark in root.findall(".//kml:Placemark", KML_NS):
        name = _node_text(placemark.find("kml:name", KML_NS)) or f"Direção {len(directions) + 1}"
        coordinates = _coordinates_for_placemark(placemark)
        if coordinates:
            directions.append(RouteDirection(name=name, coordinates=coordinates))
    return directions


def _coordinates_for_placemark(placemark: ET.Element) -> list[tuple[float, float]]:
    coordinates_node = placemark.find(".//kml:LineString/kml:coordinates", KML_NS)
    if coordinates_node is None:
        return []
    coordinates: list[tuple[float, float]] = []
    for raw_coord in (_node_text(coordinates_node) or "").split():
        parts = raw_coord.split(",")
        if len(parts) < 2:
            continue
        coordinates.append((float(parts[0]), float(parts[1])))
    return coordinates


def _node_text(node: ET.Element | None) -> str:
    return (node.text or "").strip() if node is not None else ""
