from consorcio_fenix_scraper.config import ProjectConfig


def test_project_config_defaults_match_local_docker_workflow(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    monkeypatch.delenv("CONSORCIO_FENIX_BASE_URL", raising=False)

    config = ProjectConfig()

    assert config.database_url == "postgresql+psycopg://postgres:postgres@localhost:5432/consorcio_fenix"
    assert config.log_level == "INFO"
    assert config.base_url == "https://www.consorciofenix.com.br"
    assert config.route_index_url == "https://www.consorciofenix.com.br/horarios"
    assert config.http_timeout_seconds == 20.0
    assert config.http_retries == 2
    assert config.http_rate_limit_seconds == 0.5


def test_project_config_reads_environment_overrides(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:pass@db:5432/custom")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("CONSORCIO_FENIX_BASE_URL", "https://example.test")
    monkeypatch.setenv("CONSORCIO_FENIX_HTTP_RETRIES", "5")

    config = ProjectConfig()

    assert config.database_url == "postgresql+psycopg://user:pass@db:5432/custom"
    assert config.log_level == "DEBUG"
    assert config.base_url == "https://example.test"
    assert config.route_index_url == "https://example.test/horarios"
    assert config.http_retries == 5
