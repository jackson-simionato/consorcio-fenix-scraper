from __future__ import annotations

import time
from collections.abc import Iterable
from dataclasses import dataclass
from urllib import robotparser
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup


BASE_URL = "https://www.consorciofenix.com.br"


@dataclass(frozen=True)
class FetcherConfig:
    user_agent: str = "consorcio-fenix-scraper/0.1 (+https://github.com/)"
    timeout_seconds: float = 20.0
    retries: int = 2
    rate_limit_seconds: float = 0.5


class HttpFetcher:
    def __init__(self, config: FetcherConfig | None = None) -> None:
        self.config = config or FetcherConfig()
        self.client = httpx.Client(
            headers={"User-Agent": self.config.user_agent},
            timeout=self.config.timeout_seconds,
            follow_redirects=True,
        )
        self._robots: robotparser.RobotFileParser | None = None

    def get_text(self, url: str) -> str:
        self.assert_allowed(url)
        last_error: Exception | None = None
        for attempt in range(self.config.retries + 1):
            try:
                if attempt:
                    time.sleep(self.config.rate_limit_seconds)
                response = self.client.get(url)
                response.raise_for_status()
                return response.text
            except httpx.HTTPError as exc:
                last_error = exc
        raise RuntimeError(f"Failed to fetch {url}: {last_error}") from last_error

    def assert_allowed(self, url: str) -> None:
        robots = self._load_robots(url)
        if not robots.can_fetch(self.config.user_agent, url):
            raise PermissionError(f"robots.txt disallows fetching {url}")

    def _load_robots(self, url: str) -> robotparser.RobotFileParser:
        if self._robots is not None:
            return self._robots
        robots_url = urljoin(url, "/robots.txt")
        response = self.client.get(robots_url)
        response.raise_for_status()
        parser = robotparser.RobotFileParser()
        parser.parse(response.text.splitlines())
        self._robots = parser
        return parser

    def close(self) -> None:
        self.client.close()


def parse_route_links(index_html: str, base_url: str = BASE_URL) -> list[str]:
    soup = BeautifulSoup(index_html, "html.parser")
    urls: list[str] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        href = str(anchor["href"])
        if "/horarios/" not in href or "," not in href:
            continue
        url = urljoin(base_url, href)
        if url not in seen:
            urls.append(url)
            seen.add(url)
    return urls


def limited(items: Iterable[str], limit: int | None) -> list[str]:
    values = list(items)
    return values[:limit] if limit is not None else values
