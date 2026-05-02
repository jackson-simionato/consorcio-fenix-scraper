from __future__ import annotations

import time
from collections.abc import Iterable
from dataclasses import dataclass
from urllib import robotparser
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from consorcio_fenix_scraper.config import load_config
from consorcio_fenix_scraper.logging import get_logger


BASE_URL = load_config().base_url
logger = get_logger(__name__)


@dataclass(frozen=True)
class FetcherConfig:
    user_agent: str = load_config().user_agent
    timeout_seconds: float = load_config().http_timeout_seconds
    retries: int = load_config().http_retries
    rate_limit_seconds: float = load_config().http_rate_limit_seconds


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
        return self._get_response(url).text

    def assert_allowed(self, url: str) -> None:
        robots = self._load_robots(url)
        logger.debug("Checking robots.txt permission for %s", url)
        if not robots.can_fetch(self.config.user_agent, url):
            logger.error("robots.txt disallows fetching %s", url)
            raise PermissionError(f"robots.txt disallows fetching {url}")

    def _load_robots(self, url: str) -> robotparser.RobotFileParser:
        if self._robots is not None:
            return self._robots
        robots_url = urljoin(url, "/robots.txt")
        logger.info("Fetching robots.txt: %s", robots_url)
        response = self._get_response(robots_url)
        parser = robotparser.RobotFileParser()
        parser.parse(response.text.splitlines())
        self._robots = parser
        return parser

    def _get_response(self, url: str) -> httpx.Response:
        last_error: Exception | None = None
        attempts = self.config.retries + 1
        for attempt in range(attempts):
            try:
                if attempt:
                    logger.info("Retrying fetch attempt %s/%s: %s", attempt + 1, attempts, url)
                    time.sleep(self.config.rate_limit_seconds)
                logger.debug("Fetching URL: %s", url)
                response = self.client.get(url)
                response.raise_for_status()
                return response
            except httpx.HTTPError as exc:
                last_error = exc
                logger.warning("Fetch attempt %s/%s failed for %s: %s", attempt + 1, attempts, url, exc)
        logger.error("Failed to fetch %s after %s attempts", url, attempts)
        raise RuntimeError(f"Failed to fetch {url}: {last_error}") from last_error

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
