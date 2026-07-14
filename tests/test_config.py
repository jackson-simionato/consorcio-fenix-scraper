from consorcio_fenix_scraper.config import ProjectConfig


def test_project_config_defaults_match_local_docker_workflow(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    monkeypatch.delenv("CONSORCIO_FENIX_BASE_URL", raising=False)

    config = ProjectConfig(_env_file=None)

    assert config.database_url == "postgresql+psycopg://postgres:postgres@localhost:5432/consorcio_fenix"
    assert config.log_level == "INFO"
    assert config.base_url == "https://www.consorciofenix.com.br"
    assert config.route_index_url == "https://www.consorciofenix.com.br/horarios"
    assert config.http_timeout_seconds == 20.0
    assert config.http_retries == 2
    assert config.http_rate_limit_seconds == 0.5
    assert config.http_concurrency == 4
    assert config.db_batch_rows == 10_000


def test_project_config_reads_environment_overrides(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:pass@db:5432/custom")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("CONSORCIO_FENIX_BASE_URL", "https://example.test")
    monkeypatch.setenv("CONSORCIO_FENIX_HTTP_RETRIES", "5")
    monkeypatch.setenv("CONSORCIO_FENIX_HTTP_CONCURRENCY", "7")
    monkeypatch.setenv("CONSORCIO_FENIX_DB_BATCH_ROWS", "1234")

    config = ProjectConfig(_env_file=None)

    assert config.database_url == "postgresql+psycopg://user:pass@db:5432/custom"
    assert config.log_level == "DEBUG"
    assert config.base_url == "https://example.test"
    assert config.route_index_url == "https://example.test/horarios"
    assert config.http_retries == 5
    assert config.http_concurrency == 7
    assert config.db_batch_rows == 1234


def test_project_config_reads_database_url_from_dotenv(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.chdir(tmp_path)
    dotenv_url = "postgresql+psycopg://render_user:secret@render-db:5432/render_db"
    (tmp_path / ".env").write_text(f"DATABASE_URL={dotenv_url}\n", encoding="utf-8")

    config = ProjectConfig()

    assert config.database_url == dotenv_url


def test_environment_database_url_overrides_dotenv(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    dotenv_url = "postgresql+psycopg://dotenv:secret@db:5432/app"
    env_url = "postgresql+psycopg://env:secret@db:5432/app"
    (tmp_path / ".env").write_text(f"DATABASE_URL={dotenv_url}\n", encoding="utf-8")
    monkeypatch.setenv("DATABASE_URL", env_url)

    config = ProjectConfig()

    assert config.database_url == env_url
