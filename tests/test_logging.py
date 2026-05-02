import logging

from consorcio_fenix_scraper.logging import configure_logging, get_logger


def test_configure_logging_defaults_to_info(monkeypatch):
    monkeypatch.delenv("LOG_LEVEL", raising=False)

    configure_logging()

    assert get_logger("test").getEffectiveLevel() == logging.INFO


def test_configure_logging_uses_debug_from_environment(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")

    configure_logging()

    assert get_logger("test").getEffectiveLevel() == logging.DEBUG


def test_configure_logging_invalid_environment_level_falls_back_to_info(monkeypatch, caplog):
    monkeypatch.setenv("LOG_LEVEL", "VERBOSE")

    with caplog.at_level(logging.WARNING, logger="consorcio_fenix_scraper"):
        configure_logging()
        assert get_logger("test").getEffectiveLevel() == logging.INFO

    assert "Invalid LOG_LEVEL='VERBOSE'; falling back to INFO" in caplog.text
