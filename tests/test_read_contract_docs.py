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
