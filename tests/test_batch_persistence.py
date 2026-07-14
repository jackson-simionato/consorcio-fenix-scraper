import logging
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import consorcio_fenix_scraper.db as db
from consorcio_fenix_scraper.db import Base, RouteRecord, RouteVersionRecord, ScrapeRunRecord, persist_snapshots
from consorcio_fenix_scraper.domain import FarePolicy, ParsedRoutePage, RouteSnapshot, ScrapeStatus


def _session_factory(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'batch.db'}", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)


def _snapshot(code: str) -> RouteSnapshot:
    return RouteSnapshot(
        route=ParsedRoutePage(
            code=code,
            name=f"Route {code}",
            slug=f"route-{code}",
            page_url=f"https://example.test/horarios/route-{code},{code}",
            fare_region="Regiao Unica",
            fare_policy=FarePolicy(region="Regiao Unica", cash_qrcode_pix_cents=770),
        ),
        source_hash=f"source-{code}",
    )


def test_row_weighted_batches_preserve_order_and_allow_oversized_route():
    snapshots = [_snapshot("100"), _snapshot("200"), _snapshot("300")]
    weights = [db._snapshot_row_count(snapshot) for snapshot in snapshots]

    batches = list(db._batch_snapshots(snapshots, max_rows=weights[0] + weights[1] - 1))

    assert [[snapshot.route.code for snapshot in batch] for batch in batches] == [["100"], ["200"], ["300"]]
    assert list(db._batch_snapshots([snapshots[0]], max_rows=1)) == [[snapshots[0]]]


def test_completed_batch_survives_later_failure_and_run_is_durably_failed(tmp_path, monkeypatch):
    session_factory = _session_factory(tmp_path)
    snapshots = [_snapshot("100"), _snapshot("200"), _snapshot("300")]
    real_persist_batch = db._persist_snapshot_batch
    calls = 0

    def fail_second_batch(session, run_id, batch):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("injected batch failure")
        return real_persist_batch(session, run_id, batch)

    monkeypatch.setattr(db, "_persist_snapshot_batch", fail_second_batch)

    with pytest.raises(RuntimeError, match="injected batch failure"):
        persist_snapshots(session_factory, "https://example.test/horarios", snapshots, max_batch_rows=1)

    with session_factory() as session:
        run = session.query(ScrapeRunRecord).one()
        assert run.status == ScrapeStatus.FAILED.value
        assert run.finished_at is not None
        assert run.error_summary == "injected batch failure"
        assert [route.code for route in session.query(RouteRecord).all()] == ["100"]
        assert session.query(RouteVersionRecord).count() == 1


def test_retry_reuses_progress_committed_before_failed_batch(tmp_path, monkeypatch):
    session_factory = _session_factory(tmp_path)
    snapshots = [_snapshot("100"), _snapshot("200")]
    real_persist_batch = db._persist_snapshot_batch
    calls = 0

    def fail_second_batch(session, run_id, batch):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("injected batch failure")
        return real_persist_batch(session, run_id, batch)

    monkeypatch.setattr(db, "_persist_snapshot_batch", fail_second_batch)
    with pytest.raises(RuntimeError):
        persist_snapshots(session_factory, "https://example.test/horarios", snapshots, max_batch_rows=1)

    monkeypatch.setattr(db, "_persist_snapshot_batch", real_persist_batch)
    result = persist_snapshots(session_factory, "https://example.test/horarios", snapshots, max_batch_rows=1)

    assert result.routes == 2
    with session_factory() as session:
        assert session.query(RouteRecord).count() == 2
        assert session.query(RouteVersionRecord).count() == 2
        assert [run.status for run in session.query(ScrapeRunRecord).order_by(ScrapeRunRecord.started_at)] == [
            ScrapeStatus.FAILED.value,
            ScrapeStatus.SUCCESS.value,
        ]


def test_batch_persistence_logs_rows_duration_and_throughput(tmp_path, caplog):
    session_factory = _session_factory(tmp_path)

    with caplog.at_level(logging.INFO, logger="consorcio_fenix_scraper.db"):
        persist_snapshots(session_factory, "https://example.test/horarios", [_snapshot("100")], max_batch_rows=10_000)

    assert "persistence_batch_complete" in caplog.text
    assert "proposed_rows=" in caplog.text
    assert "duration_seconds=" in caplog.text
    assert "rows_per_second=" in caplog.text
    assert "persistence_complete" in caplog.text


def test_materialization_error_is_recorded_on_scrape_run(tmp_path, monkeypatch):
    session_factory = _session_factory(tmp_path)

    def fail_materialization(_snapshot):
        raise RuntimeError("materialization failed")

    monkeypatch.setattr(db, "_snapshot_row_count", fail_materialization)

    with pytest.raises(RuntimeError, match="materialization failed"):
        persist_snapshots(session_factory, "https://example.test/horarios", [_snapshot("100")])

    with session_factory() as session:
        run = session.query(ScrapeRunRecord).one()
        assert run.status == ScrapeStatus.FAILED.value
        assert run.finished_at is not None
        assert run.error_summary == "materialization failed"


def test_success_finalization_error_falls_back_to_failed_status(tmp_path, monkeypatch):
    session_factory = _session_factory(tmp_path)
    real_finish = db._finish_scrape_run

    def fail_success(factory, run_id, status, *, error_summary=None):
        if status is ScrapeStatus.SUCCESS:
            raise RuntimeError("success finalization failed")
        return real_finish(factory, run_id, status, error_summary=error_summary)

    monkeypatch.setattr(db, "_finish_scrape_run", fail_success)

    with pytest.raises(RuntimeError, match="success finalization failed"):
        persist_snapshots(session_factory, "https://example.test/horarios", [_snapshot("100")])

    with session_factory() as session:
        run = session.query(ScrapeRunRecord).one()
        assert run.status == ScrapeStatus.FAILED.value
        assert run.finished_at is not None
        assert run.error_summary == "success finalization failed"
