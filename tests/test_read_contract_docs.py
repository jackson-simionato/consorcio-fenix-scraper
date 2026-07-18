from pathlib import Path


def test_candidate_route_direction_read_contract_is_documented():
    contract = Path("docs/candidate-route-direction-read-contract.md").read_text(encoding="utf-8")

    required_phrases = [
        "read-only",
        "current routes and current route versions",
        "Materialized Route Segment proximity",
        "not stop proximity",
        "requires materialized segments",
        "Candidate Direction Label",
        "Service Direction",
        "Route Direction",
        "ST_DWithin",
        "GROUP BY",
    ]

    for phrase in required_phrases:
        assert phrase in contract


def test_onboard_advisory_readiness_is_documented():
    contract = Path("docs/candidate-route-direction-read-contract.md").read_text(encoding="utf-8")

    required_phrases = [
        "Projected Route Position",
        "route_segments.geometry",
        "route_segments.bearing_degrees",
        "route_segments.distance_meters",
        "route_segments.cumulative_distance_meters",
        "Upcoming Exposure Window",
        "Remaining Route Exposure",
        "Sun Position",
        "Sun Exposure",
        "does not precompute",
        "75 meters",
        "Geometric Sun Exposure only",
        "temperature, weather, shadow, seat-row, or fleet-specific cabin predictions",
        "current routes and current route versions",
        "Candidate Route Direction eligibility",
        "Candidate Direction Label fallback",
        "Future advisory-app work",
    ]

    for phrase in required_phrases:
        assert phrase in contract


def test_postgres_persistence_verification_documents_the_isolated_database_gate_and_command():
    readme = Path("README.md").read_text(encoding="utf-8")
    verification = Path("docs/postgres-persistence-verification.md").read_text(encoding="utf-8")

    assert "PostgreSQL Persistence Verification" in readme
    assert "POSTGRES_TEST_DATABASE_URL" in verification
    assert "_test" in verification
    assert "tests/test_postgres_persistence.py" in verification
    assert "No performance thresholds" in verification
