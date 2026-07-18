import logging
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker

import consorcio_fenix_scraper.db as db
from consorcio_fenix_scraper.db import (
    Base,
    FareVersionRecord,
    ItineraryStepRecord,
    RouteDirectionRecord,
    RouteRecord,
    RouteSegmentRecord,
    RouteVersionRecord,
    ScheduleEntryRecord,
    ScrapeRunRecord,
    ServiceDirectionRecord,
    persist_snapshots,
)
from consorcio_fenix_scraper.domain import (
    FarePolicy,
    ParsedRoutePage,
    RouteSnapshot,
    ScrapeStatus,
)


def _session_factory(tmp_path: Path, filename: str = "batch.db"):
    engine = create_engine(f"sqlite:///{tmp_path / filename}", future=True)
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


def _normalized_database(session: Session) -> dict[str, list[tuple]]:
    version_identity_by_id = {
        version_id: (code, source_hash, map_hash)
        for version_id, code, source_hash, map_hash in session.execute(
            select(
                RouteVersionRecord.id,
                RouteRecord.code,
                RouteVersionRecord.source_hash,
                RouteVersionRecord.map_hash,
            ).join(RouteRecord, RouteRecord.id == RouteVersionRecord.route_id)
        )
    }
    direction_identity_by_id = {
        direction.id: (*version_identity_by_id[direction.route_version_id], direction.sequence)
        for direction in session.query(RouteDirectionRecord)
    }
    return {
        "versions": sorted(
            (
                code,
                source_hash,
                map_hash or "",
                is_current,
                fare_cents,
            )
            for code, source_hash, map_hash, is_current, fare_cents in session.execute(
                select(
                    RouteRecord.code,
                    RouteVersionRecord.source_hash,
                    RouteVersionRecord.map_hash,
                    RouteVersionRecord.is_current,
                    FareVersionRecord.cash_qrcode_pix_cents,
                )
                .join(RouteVersionRecord, RouteVersionRecord.route_id == RouteRecord.id)
                .outerjoin(FareVersionRecord, FareVersionRecord.id == RouteVersionRecord.fare_version_id)
            )
        ),
        "directions": sorted(
            (
                *version_identity_by_id[row.route_version_id],
                row.sequence,
                row.name,
                row.direction_kind,
                str(row.geometry),
            )
            for row in session.query(RouteDirectionRecord)
        ),
        "segments": sorted(
            (
                *direction_identity_by_id[row.route_direction_id],
                row.sequence,
                row.source_segment_sequence,
                row.source_fraction_start,
                row.source_fraction_end,
                str(row.geometry),
                round(row.bearing_degrees, 6),
                round(row.distance_meters, 6),
                round(row.cumulative_distance_meters, 6),
            )
            for row in session.query(RouteSegmentRecord)
        ),
        "services": sorted(
            (
                *version_identity_by_id[row.route_version_id],
                row.sequence,
                row.departure_label,
                row.normalized_name,
                row.direction_kind,
                row.confidence,
                row.method,
                direction_identity_by_id.get(row.route_direction_id),
            )
            for row in session.query(ServiceDirectionRecord)
        ),
        "schedules": sorted(
            (
                *version_identity_by_id[row.route_version_id],
                row.day_type,
                row.departure_label,
                row.time,
                tuple(row.flags),
            )
            for row in session.query(ScheduleEntryRecord)
        ),
        "itinerary": sorted(
            (*version_identity_by_id[row.route_version_id], row.sequence, row.name)
            for row in session.query(ItineraryStepRecord)
        ),
    }


def test_row_weighted_batches_preserve_order_and_allow_oversized_route():
    snapshots = [_snapshot("100"), _snapshot("200"), _snapshot("300")]
    weights = [db._prepare_snapshot(snapshot).row_count for snapshot in snapshots]

    batches = list(db._batch_prepared_snapshots(snapshots, max_rows=weights[0] + weights[1] - 1))

    assert [[prepared.snapshot.route.code for prepared in batch] for batch, _ in batches] == [
        ["100"],
        ["200"],
        ["300"],
    ]
    oversized_batches = list(db._batch_prepared_snapshots([snapshots[0]], max_rows=1))
    assert [[prepared.snapshot for prepared in batch] for batch, _ in oversized_batches] == [[snapshots[0]]]


def test_batch_persistence_logs_rows_duration_and_throughput(tmp_path, caplog):
    session_factory = _session_factory(tmp_path)

    with caplog.at_level(logging.INFO, logger="consorcio_fenix_scraper.db"):
        persist_snapshots(session_factory, "https://example.test/horarios", [_snapshot("100")], max_batch_rows=10_000)

    assert "persistence_batch_complete" in caplog.text
    assert "proposed_rows=" in caplog.text
    assert "duration_seconds=" in caplog.text
    assert "rows_per_second=" in caplog.text
    assert "persistence_complete" in caplog.text


def test_persistence_materializes_each_route_direction_once(tmp_path, monkeypatch, complete_snapshot_factory):
    session_factory = _session_factory(tmp_path)
    real_materialize = db.materialize_route_segments
    materialized_directions = 0

    def count_materialization(direction):
        nonlocal materialized_directions
        materialized_directions += 1
        return real_materialize(direction)

    monkeypatch.setattr(db, "materialize_route_segments", count_materialization)

    persist_snapshots(
        session_factory,
        "https://example.test/horarios",
        [complete_snapshot_factory("100")],
        max_batch_rows=10_000,
    )

    assert materialized_directions == 1


def test_cold_unchanged_and_changed_subsets_preserve_normalized_history_without_duplicate_children(
    tmp_path,
    complete_snapshot_factory,
):
    session_factory = _session_factory(tmp_path)
    initial = [complete_snapshot_factory(code) for code in ("100", "200", "300")]

    persist_snapshots(session_factory, "https://example.test/horarios", initial, max_batch_rows=10_000)
    with session_factory() as session:
        cold_database = _normalized_database(session)
    persist_snapshots(session_factory, "https://example.test/horarios", initial, max_batch_rows=10_000)
    with session_factory() as session:
        assert _normalized_database(session) == cold_database
    persist_snapshots(
        session_factory,
        "https://example.test/horarios",
        [
            complete_snapshot_factory("100", source_hash="source-b"),
            complete_snapshot_factory("200", map_hash="map-b"),
            complete_snapshot_factory("300", fare_cents=790),
        ],
        max_batch_rows=10_000,
    )

    with session_factory() as session:
        assert _normalized_database(session)["versions"] == [
            ("100", "source-a", "map-a", False, 770),
            ("100", "source-b", "map-a", True, 770),
            ("200", "source-a", "map-a", False, 770),
            ("200", "source-a", "map-b", True, 770),
            ("300", "source-a", "map-a", True, 790),
        ]
        assert session.query(FareVersionRecord).count() == 4
        assert session.query(RouteDirectionRecord).count() == 5
        assert session.query(RouteSegmentRecord).count() == 5
        assert session.query(ServiceDirectionRecord).count() == 5
        assert session.query(ScheduleEntryRecord).count() == 5
        assert session.query(ItineraryStepRecord).count() == 5
        assert [run.status for run in session.query(ScrapeRunRecord).order_by(ScrapeRunRecord.started_at)] == [
            ScrapeStatus.SUCCESS.value,
            ScrapeStatus.SUCCESS.value,
            ScrapeStatus.SUCCESS.value,
        ]


@pytest.mark.parametrize(
    ("failed_batch", "committed_codes"),
    [
        (1, []),
        (2, ["100"]),
        (3, ["100", "200"]),
    ],
)
def test_first_middle_and_final_batch_failures_roll_back_only_the_active_batch_and_retry_reuses_progress(
    tmp_path,
    failed_batch,
    committed_codes,
    complete_snapshot_factory,
):
    session_factory = _session_factory(tmp_path)
    snapshots = [complete_snapshot_factory(code) for code in ("100", "200", "300")]
    calls = 0

    def inject_failure(_connection, _cursor, statement, _parameters, _context, _executemany):
        nonlocal calls
        if not statement.lstrip().upper().startswith("INSERT INTO ROUTES"):
            return
        calls += 1
        if calls == failed_batch:
            raise RuntimeError(f"injected failure in batch {failed_batch}")

    engine = session_factory.kw["bind"]
    event.listen(engine, "before_cursor_execute", inject_failure)
    try:
        with pytest.raises(RuntimeError, match=f"injected failure in batch {failed_batch}"):
            persist_snapshots(session_factory, "https://example.test/horarios", snapshots, max_batch_rows=1)
    finally:
        event.remove(engine, "before_cursor_execute", inject_failure)

    with session_factory() as session:
        failed_run = session.query(ScrapeRunRecord).one()
        assert failed_run.status == ScrapeStatus.FAILED.value
        assert failed_run.finished_at is not None
        assert failed_run.error_summary == f"injected failure in batch {failed_batch}"
        assert [route.code for route in session.query(RouteRecord).order_by(RouteRecord.code)] == committed_codes
        committed_database = _normalized_database(session)

    reference_factory = _session_factory(tmp_path, "reference.db")
    if committed_codes:
        persist_snapshots(
            reference_factory,
            "https://example.test/horarios",
            snapshots[: failed_batch - 1],
            max_batch_rows=1,
        )
    with reference_factory() as session:
        assert committed_database == _normalized_database(session)

    retry_result = persist_snapshots(session_factory, "https://example.test/horarios", snapshots, max_batch_rows=1)

    with session_factory() as session:
        assert retry_result.routes == 3
        assert [route.code for route in session.query(RouteRecord).order_by(RouteRecord.code)] == ["100", "200", "300"]
        assert session.query(RouteVersionRecord).count() == 3
        assert session.query(RouteDirectionRecord).count() == 3
        assert session.query(RouteSegmentRecord).count() == 3
        assert session.query(ServiceDirectionRecord).count() == 3
        assert session.query(ScheduleEntryRecord).count() == 3
        assert session.query(ItineraryStepRecord).count() == 3
        assert [run.status for run in session.query(ScrapeRunRecord).order_by(ScrapeRunRecord.started_at)] == [
            ScrapeStatus.FAILED.value,
            ScrapeStatus.SUCCESS.value,
        ]


def test_materialization_error_is_recorded_on_scrape_run(tmp_path, monkeypatch):
    session_factory = _session_factory(tmp_path)

    def fail_materialization(_snapshot):
        raise RuntimeError("materialization failed")

    monkeypatch.setattr(db, "_prepare_snapshot", fail_materialization)

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


def test_failed_status_finalization_retries_in_a_fresh_control_transaction(tmp_path, monkeypatch):
    session_factory = _session_factory(tmp_path)
    real_finish = db._finish_scrape_run
    failed_finalization_attempts = 0

    def fail_first_failed_status(factory, run_id, status, *, error_summary=None):
        nonlocal failed_finalization_attempts
        if status is ScrapeStatus.FAILED:
            failed_finalization_attempts += 1
            if failed_finalization_attempts == 1:
                raise RuntimeError("transient control transaction failure")
        return real_finish(factory, run_id, status, error_summary=error_summary)

    def fail_materialization(_snapshot):
        raise RuntimeError("materialization failed")

    monkeypatch.setattr(db, "_finish_scrape_run", fail_first_failed_status)
    monkeypatch.setattr(db, "_prepare_snapshot", fail_materialization)

    with pytest.raises(RuntimeError, match="materialization failed"):
        persist_snapshots(session_factory, "https://example.test/horarios", [_snapshot("100")])

    with session_factory() as session:
        run = session.query(ScrapeRunRecord).one()
        assert failed_finalization_attempts == 2
        assert run.status == ScrapeStatus.FAILED.value
        assert run.finished_at is not None
        assert run.error_summary == "materialization failed"
