import httpx

from consorcio_fenix_scraper.http import AsyncHttpFetcher, FetcherConfig, HttpFetcher


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


def test_async_fetcher_retries_transient_robots_fetch_failure(monkeypatch):
    async def run() -> None:
        fetcher = AsyncHttpFetcher(FetcherConfig(retries=1, rate_limit_seconds=0))
        calls: list[str] = []

        async def fake_get(url: str):
            calls.append(url)
            if url.endswith("/robots.txt") and calls.count(url) == 1:
                raise httpx.ConnectError("connection reset")
            if url.endswith("/robots.txt"):
                return httpx.Response(200, text="User-agent: *\nAllow: /\n", request=httpx.Request("GET", url))
            return httpx.Response(200, text="route index", request=httpx.Request("GET", url))

        monkeypatch.setattr(fetcher.client, "get", fake_get)

        assert await fetcher.get_text("https://example.test/horarios") == "route index"
        assert calls == [
            "https://example.test/robots.txt",
            "https://example.test/robots.txt",
            "https://example.test/horarios",
        ]
        await fetcher.close()

    import asyncio

    asyncio.run(run())


def test_async_fetcher_loads_robots_once_for_concurrent_requests(monkeypatch):
    async def run() -> None:
        fetcher = AsyncHttpFetcher(FetcherConfig(retries=0, rate_limit_seconds=0))
        calls: list[str] = []

        async def fake_get(url: str):
            calls.append(url)
            return httpx.Response(200, text="User-agent: *\nAllow: /\n", request=httpx.Request("GET", url))

        monkeypatch.setattr(fetcher.client, "get", fake_get)

        import asyncio

        await asyncio.gather(
            fetcher.get_text("https://example.test/horarios/a,1"),
            fetcher.get_text("https://example.test/horarios/b,2"),
        )

        assert calls.count("https://example.test/robots.txt") == 1
        await fetcher.close()

    import asyncio

    asyncio.run(run())
