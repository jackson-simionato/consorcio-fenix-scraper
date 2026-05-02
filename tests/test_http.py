import httpx

from consorcio_fenix_scraper.http import FetcherConfig, HttpFetcher


def test_fetcher_retries_transient_robots_fetch_failure(monkeypatch):
    fetcher = HttpFetcher(FetcherConfig(retries=1, rate_limit_seconds=0))
    calls: list[str] = []

    def fake_get(url: str):
        calls.append(url)
        if url.endswith("/robots.txt") and calls.count(url) == 1:
            raise httpx.ConnectError("connection reset")
        if url.endswith("/robots.txt"):
            return httpx.Response(200, text="User-agent: *\nAllow: /\n", request=httpx.Request("GET", url))
        return httpx.Response(200, text="route index", request=httpx.Request("GET", url))

    monkeypatch.setattr(fetcher.client, "get", fake_get)

    assert fetcher.get_text("https://example.test/horarios") == "route index"
    assert calls == [
        "https://example.test/robots.txt",
        "https://example.test/robots.txt",
        "https://example.test/horarios",
    ]
