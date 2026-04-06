#!/usr/bin/env python3
"""
Test the Lambda handlers with mocked Citibike data to verify edge case behavior.

Usage:
    uv run scripts/test_mock.py
    uv run scripts/test_mock.py -v  # verbose output
"""

import argparse
import json
import sys
from pathlib import Path
from unittest.mock import patch
from dataclasses import dataclass

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


@dataclass
class MockStationResult:
    """Mock station result from GBFS."""
    station_id: str
    name: str
    docks_available: int
    bikes_available: int
    ebikes_available: int
    classic_bikes_available: int
    is_installed: bool = True
    is_renting: bool = True
    is_returning: bool = True


@dataclass
class MockParkingSummary:
    """Mock parking summary."""
    station_ids: list
    available_spots: int
    stations: list
    as_of: str = "2024-01-01T00:00:00Z"
    ttl_seconds: int = 60


TEST_PROFILE = [
    {"name": "43rd and Madison", "id": "station-43rd", "primary": True},
    {"name": "grand central", "primary": True, "stations": [
        {"id": "station-gc-north", "name": "north"},
        {"id": "station-gc-south", "name": "south"},
    ]},
    {"name": "40th", "stations": [
        {"id": "station-40th-east", "name": "east"},
        {"id": "station-40th-west", "name": "west"},
    ]},
]


def make_mock_summary(station_data: dict) -> MockParkingSummary:
    """
    Create a mock parking summary from station data dict.

    station_data format: {
        "station-id": {"docks": 10, "ebikes": 5, "classic": 3},
        ...
    }
    """
    stations = []
    for station_id, data in station_data.items():
        ebikes = data.get("ebikes", 0)
        classic = data.get("classic", 0)
        stations.append(MockStationResult(
            station_id=station_id,
            name=station_id,
            docks_available=data.get("docks", 0),
            bikes_available=ebikes + classic,
            ebikes_available=ebikes,
            classic_bikes_available=classic,
        ))

    return MockParkingSummary(
        station_ids=list(station_data.keys()),
        available_spots=sum(s.docks_available for s in stations),
        stations=stations,
    )


def make_event(count_type: str) -> dict:
    body = {"profile": TEST_PROFILE, "type": count_type}
    return {"headers": {}, "body": json.dumps(body)}


def run_test(name: str, station_data: dict, count_type: str, expected_contains: list, verbose: bool = False):
    """Run a single test case."""
    from lambda_app.handler import citibike_check_english, citibike_check

    mock_summary = make_mock_summary(station_data)
    with patch("lambda_app.handler.compute_parking_summary", return_value=mock_summary):
        event = make_event(count_type)

        # Get English response
        response = citibike_check_english(event, None)
        body = response["body"]

        # Get JSON response for verbose output
        json_response = citibike_check(event, None)
        json_body = json.loads(json_response["body"])

        # Check expectations
        passed = all(exp in body for exp in expected_contains)
        status = "✓" if passed else "✗"

        print(f"{status} {name}")
        if verbose or not passed:
            print(f"  Input: {station_data}")
            print(f"  Output: {body}")
            if not passed:
                print(f"  Expected to contain: {expected_contains}")
            print(f"  JSON: {json.dumps(json_body, indent=4)}")
            print()

        return passed


def main():
    parser = argparse.ArgumentParser(description="Test with mocked Citibike data")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    args = parser.parse_args()

    print("=" * 60)
    print("DOCKS TESTS")
    print("=" * 60)

    results = []

    # Test 1: Plenty of docks everywhere - should show primary only, collapsed
    results.append(run_test(
        "Plenty of docks - primary only, collapsed",
        {
            "station-43rd": {"docks": 10},
            "station-gc-north": {"docks": 15},
            "station-gc-south": {"docks": 12},
            "station-40th-east": {"docks": 8},
            "station-40th-west": {"docks": 5},
        },
        "docks",
        ["10 docks at 43rd and Madison", "27 docks at grand central"],
        args.verbose
    ))

    # Test 2: GC north empty, south has docks - should expand GC
    results.append(run_test(
        "GC north empty - should expand group",
        {
            "station-43rd": {"docks": 10},
            "station-gc-north": {"docks": 0},
            "station-gc-south": {"docks": 12},
            "station-40th-east": {"docks": 8},
            "station-40th-west": {"docks": 5},
        },
        "docks",
        ["10 docks at 43rd and Madison", "0 docks at grand central north", "12 docks at grand central south"],
        args.verbose
    ))

    # Test 3: Primary low (<=3) - should show backups
    results.append(run_test(
        "Primary low (<=3) - should show backups",
        {
            "station-43rd": {"docks": 1},
            "station-gc-north": {"docks": 2},
            "station-gc-south": {"docks": 0},
            "station-40th-east": {"docks": 8},
            "station-40th-west": {"docks": 5},
        },
        "docks",
        ["1 docks at 43rd and Madison", "2 docks at grand central", "13 docks at 40th"],
        args.verbose
    ))

    # Test 4: Primary empty - should show backups expanded
    results.append(run_test(
        "Primary empty - should show backups",
        {
            "station-43rd": {"docks": 0},
            "station-gc-north": {"docks": 0},
            "station-gc-south": {"docks": 0},
            "station-40th-east": {"docks": 8},
            "station-40th-west": {"docks": 5},
        },
        "docks",
        ["0 docks at 43rd and Madison", "0 docks at grand central", "13 docks at 40th"],
        args.verbose
    ))

    # Test 5: Everything empty
    results.append(run_test(
        "Everything empty",
        {
            "station-43rd": {"docks": 0},
            "station-gc-north": {"docks": 0},
            "station-gc-south": {"docks": 0},
            "station-40th-east": {"docks": 0},
            "station-40th-west": {"docks": 0},
        },
        "docks",
        ["0 docks at 43rd and Madison", "0 docks at grand central", "0 docks at 40th"],
        args.verbose
    ))

    print()
    print("=" * 60)
    print("BIKES TESTS")
    print("=" * 60)

    # Test 6: Plenty of ebikes - should show ebikes only, collapsed
    results.append(run_test(
        "Plenty of ebikes - ebikes only, collapsed",
        {
            "station-43rd": {"ebikes": 5, "classic": 3},
            "station-gc-north": {"ebikes": 8, "classic": 10},
            "station-gc-south": {"ebikes": 4, "classic": 6},
            "station-40th-east": {"ebikes": 3, "classic": 5},
            "station-40th-west": {"ebikes": 2, "classic": 4},
        },
        "bikes",
        ["5 ebikes at 43rd and Madison", "12 ebikes at grand central"],
        args.verbose
    ))

    # Test 7: GC north no ebikes - should expand
    results.append(run_test(
        "GC north no ebikes - should expand group",
        {
            "station-43rd": {"ebikes": 5, "classic": 3},
            "station-gc-north": {"ebikes": 0, "classic": 10},
            "station-gc-south": {"ebikes": 4, "classic": 6},
            "station-40th-east": {"ebikes": 3, "classic": 5},
            "station-40th-west": {"ebikes": 2, "classic": 4},
        },
        "bikes",
        ["5 ebikes at 43rd and Madison", "0 ebikes at grand central north", "4 ebikes at grand central south"],
        args.verbose
    ))

    # Test 8: Low ebikes (<3) - should show classic and backups
    results.append(run_test(
        "Low ebikes (<3) - should show classic and backups",
        {
            "station-43rd": {"ebikes": 1, "classic": 5},
            "station-gc-north": {"ebikes": 1, "classic": 10},
            "station-gc-south": {"ebikes": 0, "classic": 6},
            "station-40th-east": {"ebikes": 3, "classic": 5},
            "station-40th-west": {"ebikes": 2, "classic": 4},
        },
        "bikes",
        ["1 ebikes at 43rd and Madison", "1 ebikes at grand central", "classic", "40th"],
        args.verbose
    ))

    # Test 9: No ebikes anywhere - should show classic
    results.append(run_test(
        "No ebikes - should show classic",
        {
            "station-43rd": {"ebikes": 0, "classic": 5},
            "station-gc-north": {"ebikes": 0, "classic": 10},
            "station-gc-south": {"ebikes": 0, "classic": 6},
            "station-40th-east": {"ebikes": 0, "classic": 5},
            "station-40th-west": {"ebikes": 0, "classic": 4},
        },
        "bikes",
        ["0 ebikes at 43rd and Madison", "0 ebikes at grand central", "classic"],
        args.verbose
    ))

    print()
    print("=" * 60)
    passed = sum(results)
    total = len(results)
    print(f"Results: {passed}/{total} tests passed")

    if passed < total:
        sys.exit(1)


if __name__ == "__main__":
    main()
