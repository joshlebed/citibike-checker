import json
import sys
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


@dataclass
class MockStationResult:
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
    station_ids: list
    available_spots: int
    stations: list
    as_of: str = "2024-01-01T00:00:00Z"
    ttl_seconds: int = 60


WORK_PROFILE = [
    {"name": "43rd and Madison", "id": "station-43rd", "primary": True},
    {
        "name": "grand central",
        "primary": True,
        "stations": [
            {"id": "station-gc-north", "name": "north"},
            {"id": "station-gc-south", "name": "south"},
        ],
    },
    {
        "name": "40th",
        "stations": [
            {"id": "station-40th-east", "name": "east"},
            {"id": "station-40th-west", "name": "west"},
        ],
    },
]


def make_event(profile=None, q=None, count_type=None):
    body = {}
    if profile is not None:
        body["profile"] = profile
    if q is not None:
        body["q"] = q
    if count_type is not None:
        body["type"] = count_type
    return {"headers": {}, "body": json.dumps(body)}


def make_mock_summary(station_data):
    stations = []
    for station_id, data in station_data.items():
        ebikes = data.get("ebikes", 0)
        classic = data.get("classic", 0)
        stations.append(
            MockStationResult(
                station_id=station_id,
                name=station_id,
                docks_available=data.get("docks", 0),
                bikes_available=ebikes + classic,
                ebikes_available=ebikes,
                classic_bikes_available=classic,
            )
        )
    return MockParkingSummary(
        station_ids=list(station_data.keys()),
        available_spots=sum(s.docks_available for s in stations),
        stations=stations,
    )


PLENTY_OF_DOCKS = {
    "station-43rd": {"docks": 10},
    "station-gc-north": {"docks": 15},
    "station-gc-south": {"docks": 12},
    "station-40th-east": {"docks": 8},
    "station-40th-west": {"docks": 5},
}

PLENTY_OF_BIKES = {
    "station-43rd": {"ebikes": 5, "classic": 3},
    "station-gc-north": {"ebikes": 8, "classic": 10},
    "station-gc-south": {"ebikes": 4, "classic": 6},
    "station-40th-east": {"ebikes": 3, "classic": 5},
    "station-40th-west": {"ebikes": 2, "classic": 4},
}

LOW_EBIKES = {
    "station-43rd": {"ebikes": 1, "classic": 3},
    "station-gc-north": {"ebikes": 0, "classic": 10},
    "station-gc-south": {"ebikes": 1, "classic": 6},
    "station-40th-east": {"ebikes": 0, "classic": 5},
    "station-40th-west": {"ebikes": 2, "classic": 4},
}

ZERO_EBIKES = {
    "station-43rd": {"ebikes": 0, "classic": 3},
    "station-gc-north": {"ebikes": 0, "classic": 10},
    "station-gc-south": {"ebikes": 0, "classic": 6},
    "station-40th-east": {"ebikes": 0, "classic": 5},
    "station-40th-west": {"ebikes": 0, "classic": 4},
}

ZERO_BIKES = {
    "station-43rd": {"ebikes": 0, "classic": 0},
    "station-gc-north": {"ebikes": 0, "classic": 0},
    "station-gc-south": {"ebikes": 0, "classic": 0},
    "station-40th-east": {"ebikes": 0, "classic": 0},
    "station-40th-west": {"ebikes": 0, "classic": 0},
}


class TestCitibikeCheckEnglish:
    def test_docks_default(self):
        """No q param defaults to docks."""
        event = make_event(profile=WORK_PROFILE)
        mock = make_mock_summary(PLENTY_OF_DOCKS)
        with patch(
            "lambda_app.handler.compute_parking_summary", return_value=mock
        ):
            from lambda_app.handler import citibike_check_english

            resp = citibike_check_english(event, None)
        assert resp["statusCode"] == 200
        assert "10 docks at 43rd and Madison" in resp["body"]
        assert "27 docks at grand central" in resp["body"]

    def test_bikes_query(self):
        """q=bikes returns bike counts; early-stops when enough ebikes found."""
        event = make_event(profile=WORK_PROFILE, q="bikes")
        mock = make_mock_summary(PLENTY_OF_BIKES)
        with patch(
            "lambda_app.handler.compute_parking_summary", return_value=mock
        ):
            from lambda_app.handler import citibike_check_english

            resp = citibike_check_english(event, None)
        assert resp["statusCode"] == 200
        # 43rd has 5 ebikes (>= threshold), so we stop there
        assert "5 ebikes at 43rd and Madison" in resp["body"]
        assert "grand central" not in resp["body"]

    def test_type_override(self):
        """Explicit type param overrides q."""
        event = make_event(
            profile=WORK_PROFILE, q="docks", count_type="bikes"
        )
        mock = make_mock_summary(PLENTY_OF_BIKES)
        with patch(
            "lambda_app.handler.compute_parking_summary", return_value=mock
        ):
            from lambda_app.handler import citibike_check_english

            resp = citibike_check_english(event, None)
        assert resp["statusCode"] == 200
        assert "ebikes" in resp["body"]

    def test_missing_profile_400(self):
        """No profile in body returns 400."""
        event = make_event()
        from lambda_app.handler import citibike_check_english

        resp = citibike_check_english(event, None)
        assert resp["statusCode"] == 400
        assert "profile" in resp["body"].lower()

    def test_empty_profile_400(self):
        """Empty profile array returns 400."""
        event = make_event(profile=[])
        from lambda_app.handler import citibike_check_english

        resp = citibike_check_english(event, None)
        assert resp["statusCode"] == 400

    def test_bikes_skips_empty_racks(self):
        """Stations with 0 ebikes are not mentioned."""
        event = make_event(profile=WORK_PROFILE, q="bikes")
        mock = make_mock_summary(LOW_EBIKES)
        with patch(
            "lambda_app.handler.compute_parking_summary", return_value=mock
        ):
            from lambda_app.handler import citibike_check_english

            resp = citibike_check_english(event, None)
        assert resp["statusCode"] == 200
        assert "0 ebikes" not in resp["body"]

    def test_bikes_low_ebikes_includes_backups(self):
        """When primary ebikes are low, backup stations with ebikes appear."""
        event = make_event(profile=WORK_PROFILE, q="bikes")
        mock = make_mock_summary(LOW_EBIKES)
        with patch(
            "lambda_app.handler.compute_parking_summary", return_value=mock
        ):
            from lambda_app.handler import citibike_check_english

            resp = citibike_check_english(event, None)
        assert resp["statusCode"] == 200
        # Primary: 43rd=1, gc-south=1 (gc-north skipped, 0 ebikes)
        assert "1 ebikes at 43rd and Madison" in resp["body"]
        assert "1 ebikes at grand central south" in resp["body"]
        # Backup 40th-west has 2 ebikes, pushing accumulated to 4 >= 3 → stop
        assert "2 ebikes at 40th west" in resp["body"]
        # No classic fallback since accumulated >= 3
        assert "classic" not in resp["body"]

    def test_bikes_zero_ebikes_classic_fallback(self):
        """When no ebikes anywhere, falls back to classic bikes."""
        event = make_event(profile=WORK_PROFILE, q="bikes")
        mock = make_mock_summary(ZERO_EBIKES)
        with patch(
            "lambda_app.handler.compute_parking_summary", return_value=mock
        ):
            from lambda_app.handler import citibike_check_english

            resp = citibike_check_english(event, None)
        assert resp["statusCode"] == 200
        assert "ebikes" not in resp["body"]
        assert "classic at 43rd and Madison" in resp["body"]
        assert "classic at grand central" in resp["body"]

    def test_bikes_no_bikes_at_all(self):
        """When no bikes of any kind, returns clear message."""
        event = make_event(profile=WORK_PROFILE, q="bikes")
        mock = make_mock_summary(ZERO_BIKES)
        with patch(
            "lambda_app.handler.compute_parking_summary", return_value=mock
        ):
            from lambda_app.handler import citibike_check_english

            resp = citibike_check_english(event, None)
        assert resp["statusCode"] == 200
        assert resp["body"] == "No bikes available"


class TestCitibikeCheck:
    def test_docks_json(self):
        """JSON endpoint returns structured docks data."""
        event = make_event(profile=WORK_PROFILE)
        mock = make_mock_summary(PLENTY_OF_DOCKS)
        with patch(
            "lambda_app.handler.compute_parking_summary", return_value=mock
        ):
            from lambda_app.handler import citibike_check

            resp = citibike_check(event, None)
        assert resp["statusCode"] == 200
        data = json.loads(resp["body"])
        assert data["type"] == "docks"
        assert len(data["stations"]) > 0

    def test_bikes_json(self):
        """JSON endpoint returns structured bikes data."""
        event = make_event(profile=WORK_PROFILE, q="bikes")
        mock = make_mock_summary(PLENTY_OF_BIKES)
        with patch(
            "lambda_app.handler.compute_parking_summary", return_value=mock
        ):
            from lambda_app.handler import citibike_check

            resp = citibike_check(event, None)
        assert resp["statusCode"] == 200
        data = json.loads(resp["body"])
        assert data["type"] == "bikes"

    def test_missing_profile_400(self):
        """No profile in body returns 400."""
        event = make_event()
        from lambda_app.handler import citibike_check

        resp = citibike_check(event, None)
        assert resp["statusCode"] == 400
