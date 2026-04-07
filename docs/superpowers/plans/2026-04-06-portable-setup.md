# Portable Setup & Stateless Server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Lambda stateless (station config in each request) and build a browser-based station picker for generating Siri Shortcut configs.

**Architecture:** The Lambda drops all auth and server-side config — the full station profile is sent in each POST body. A static web app (GitHub Pages) lets users pick stations on a Leaflet map and generates the JSON payload + Shortcut setup instructions.

**Tech Stack:** Python 3.11 (Lambda), Leaflet.js + OpenStreetMap + Nominatim (web app), AWS SAM (deployment), pytest (tests)

**Spec:** `docs/superpowers/specs/2026-04-06-portable-setup-design.md`

---

## File Map

### Modified
- `src/lambda_app/handler.py` — remove auth, accept profile from POST body, inline `get_all_station_ids`
- `template.yaml` — change `/citibike-check` from GET to POST
- `deploy.sh` — remove `config.json` copy step
- `.gitignore` — allow `docs/**`, add `josh-profiles.json`
- `scripts/test_mock.py` — update to new handler interface (no auth, profile in body)
- `scripts/test_local.py` — read from `josh-profiles.json` instead of `config.json`
- `scripts/refresh_stations.sh` — also build slim stations for web app
- `pyproject.toml` — add pytest to dev dependencies

### Created
- `tests/test_handler.py` — pytest tests for stateless handler
- `docs/index.html` — station picker web app
- `docs/stations.json` — slim station data (name, id, lat, lon)
- `scripts/build_stations_web.py` — script to build slim stations.json

### Deleted
- `src/lambda_app/config.py` — no longer needed (auth + config lookup removed)
- `config.example.json` — no longer needed (no server-side config)

---

### Task 1: Write Tests for Stateless Handler

**Files:**
- Create: `tests/test_handler.py`
- Modify: `pyproject.toml`

- [ ] **Step 1: Add pytest to dev dependencies**

In `pyproject.toml`, change the dev dependency group:

```toml
[dependency-groups]
dev = ["pytest>=8.0"]
```

Run: `uv sync`

- [ ] **Step 2: Write test file**

Create `tests/test_handler.py`:

```python
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
        """q=bikes returns bike counts."""
        event = make_event(profile=WORK_PROFILE, q="bikes")
        mock = make_mock_summary(PLENTY_OF_BIKES)
        with patch(
            "lambda_app.handler.compute_parking_summary", return_value=mock
        ):
            from lambda_app.handler import citibike_check_english

            resp = citibike_check_english(event, None)
        assert resp["statusCode"] == 200
        assert "5 ebikes at 43rd and Madison" in resp["body"]
        assert "12 ebikes at grand central" in resp["body"]

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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_handler.py -v`

Expected: Tests fail because the current handler expects an API key and doesn't read `profile` from the body. The `test_missing_profile_400` and `test_empty_profile_400` tests will return 401 (unauthorized) instead of 400. The other tests will also return 401.

- [ ] **Step 4: Commit**

```bash
git add tests/test_handler.py pyproject.toml
git commit -m "Add pytest tests for stateless handler interface"
```

---

### Task 2: Refactor Handler to Stateless

**Files:**
- Modify: `src/lambda_app/handler.py`

The core logic (`_process_profile`, `_format_docks_english`, `_format_bikes_english`, `_format_docks_json`, `_format_bikes_json`, `StationData`, `EntryResult`) is unchanged. Only the entry points and helper functions change.

- [ ] **Step 1: Rewrite handler.py**

Replace the full contents of `src/lambda_app/handler.py` with:

```python
import json
import logging
import os
from dataclasses import dataclass

from citibike_parking.gbfs import compute_parking_summary

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Threshold: if primary availability is at or below this, also show backups
LOW_AVAILABILITY_THRESHOLD = 3


@dataclass
class StationData:
    """Data for a single station."""

    id: str
    name: str
    docks: int
    ebikes: int
    classic: int

    @property
    def bikes(self) -> int:
        return self.ebikes + self.classic


@dataclass
class EntryResult:
    """Processed result for a config entry (single station or group)."""

    name: str
    is_primary: bool
    is_group: bool
    stations: list[StationData]

    @property
    def total_docks(self) -> int:
        return sum(s.docks for s in self.stations)

    @property
    def total_ebikes(self) -> int:
        return sum(s.ebikes for s in self.stations)

    @property
    def total_classic(self) -> int:
        return sum(s.classic for s in self.stations)

    @property
    def total_bikes(self) -> int:
        return self.total_ebikes + self.total_classic

    @property
    def first_has_docks(self) -> bool:
        return self.stations[0].docks > 0 if self.stations else False

    @property
    def first_has_ebikes(self) -> bool:
        return self.stations[0].ebikes > 0 if self.stations else False


def _get_body(event) -> dict:
    """Parse JSON body from the request."""
    body = event.get("body")
    if not body:
        return {}
    if isinstance(body, dict):
        return body
    try:
        return json.loads(body)
    except (json.JSONDecodeError, TypeError):
        return {}


def _resolve_type(body: dict) -> str:
    """Determine count type (docks or bikes) from request body."""
    type_param = body.get("type")
    if type_param in ("docks", "bikes"):
        return type_param
    q = body.get("q", "")
    if isinstance(q, str) and "bike" in q.lower():
        return "bikes"
    return "docks"


def _get_all_station_ids(profile: list) -> list[str]:
    """Extract all station IDs from a profile configuration."""
    ids = []
    for entry in profile:
        if "id" in entry:
            ids.append(entry["id"])
        elif "stations" in entry:
            for station in entry["stations"]:
                ids.append(station["id"])
    return ids


def _fetch_station_data(profile: list) -> dict[str, StationData]:
    """Fetch real-time data for all stations in a profile."""
    station_ids = _get_all_station_ids(profile)

    summary = compute_parking_summary(
        station_ids,
        station_status_url=os.environ.get(
            "GBFS_STATION_STATUS_URL",
            "https://gbfs.citibikenyc.com/gbfs/en/station_status.json",
        ),
        station_information_url=os.environ.get(
            "GBFS_STATION_INFORMATION_URL",
            "https://gbfs.citibikenyc.com/gbfs/en/station_information.json",
        ),
        timeout_s=float(os.environ.get("GBFS_TIMEOUT_S", "8")),
    )

    return {
        s.station_id: StationData(
            id=s.station_id,
            name=s.name or "",
            docks=s.docks_available,
            ebikes=s.ebikes_available,
            classic=s.classic_bikes_available,
        )
        for s in summary.stations
    }


def _process_profile(
    profile: list, station_data: dict[str, StationData]
) -> list[EntryResult]:
    """Process a profile configuration into EntryResults with real-time data."""
    results = []

    for entry in profile:
        is_primary = entry.get("primary", False)

        if "id" in entry:
            data = station_data.get(entry["id"])
            if data:
                results.append(
                    EntryResult(
                        name=entry["name"],
                        is_primary=is_primary,
                        is_group=False,
                        stations=[
                            StationData(
                                id=entry["id"],
                                name=entry["name"],
                                docks=data.docks,
                                ebikes=data.ebikes,
                                classic=data.classic,
                            )
                        ],
                    )
                )
        elif "stations" in entry:
            group_stations = []
            for station in entry["stations"]:
                data = station_data.get(station["id"])
                if data:
                    group_stations.append(
                        StationData(
                            id=station["id"],
                            name=station["name"],
                            docks=data.docks,
                            ebikes=data.ebikes,
                            classic=data.classic,
                        )
                    )

            if group_stations:
                results.append(
                    EntryResult(
                        name=entry["name"],
                        is_primary=is_primary,
                        is_group=True,
                        stations=group_stations,
                    )
                )

    return results


def _format_docks_english(entries: list[EntryResult]) -> str:
    """Format dock availability as English sentence."""
    primary_entries = [e for e in entries if e.is_primary]
    backup_entries = [e for e in entries if not e.is_primary]

    total_primary_docks = sum(e.total_docks for e in primary_entries)
    include_backups = total_primary_docks <= LOW_AVAILABILITY_THRESHOLD

    entries_to_report = primary_entries + (backup_entries if include_backups else [])

    parts = []
    for entry in entries_to_report:
        if not entry.is_group:
            parts.append(f"{entry.total_docks} docks at {entry.name}")
        else:
            if entry.first_has_docks:
                parts.append(f"{entry.total_docks} docks at {entry.name}")
            else:
                for station in entry.stations:
                    parts.append(
                        f"{station.docks} docks at {entry.name} {station.name}"
                    )

    if not parts:
        return "No stations configured"

    return ", ".join(parts)


def _format_bikes_english(entries: list[EntryResult]) -> str:
    """Format bike availability as English sentence."""
    primary_entries = [e for e in entries if e.is_primary]
    backup_entries = [e for e in entries if not e.is_primary]

    total_primary_ebikes = sum(e.total_ebikes for e in primary_entries)
    include_classic = total_primary_ebikes < LOW_AVAILABILITY_THRESHOLD
    include_backups = total_primary_ebikes < LOW_AVAILABILITY_THRESHOLD

    entries_to_report = primary_entries + (backup_entries if include_backups else [])

    parts = []

    for entry in entries_to_report:
        if not entry.is_group:
            parts.append(f"{entry.total_ebikes} ebikes at {entry.name}")
        else:
            if entry.first_has_ebikes:
                parts.append(f"{entry.total_ebikes} ebikes at {entry.name}")
            else:
                for station in entry.stations:
                    parts.append(
                        f"{station.ebikes} ebikes at {entry.name} {station.name}"
                    )

    if include_classic:
        classic_parts = []
        for entry in entries_to_report:
            if not entry.is_group:
                classic_parts.append(f"{entry.total_classic} classic at {entry.name}")
            else:
                classic_parts.append(f"{entry.total_classic} classic at {entry.name}")

        if classic_parts:
            parts.append("also " + ", ".join(classic_parts))

    if not parts:
        return "No stations configured"

    return ", ".join(parts)


def _format_docks_json(entries: list[EntryResult]) -> dict:
    """Format dock availability as JSON."""
    primary_entries = [e for e in entries if e.is_primary]
    backup_entries = [e for e in entries if not e.is_primary]

    total_primary_docks = sum(e.total_docks for e in primary_entries)
    include_backups = total_primary_docks <= LOW_AVAILABILITY_THRESHOLD

    entries_to_report = primary_entries + (backup_entries if include_backups else [])

    stations = []
    for entry in entries_to_report:
        if not entry.is_group:
            stations.append(
                {
                    "name": entry.name,
                    "docks": entry.total_docks,
                    "primary": entry.is_primary,
                }
            )
        else:
            if entry.first_has_docks:
                stations.append(
                    {
                        "name": entry.name,
                        "docks": entry.total_docks,
                        "primary": entry.is_primary,
                        "collapsed": True,
                    }
                )
            else:
                for station in entry.stations:
                    stations.append(
                        {
                            "name": f"{entry.name} {station.name}",
                            "docks": station.docks,
                            "primary": entry.is_primary,
                        }
                    )

    return {
        "type": "docks",
        "total_primary": total_primary_docks,
        "showing_backups": include_backups,
        "stations": stations,
    }


def _format_bikes_json(entries: list[EntryResult]) -> dict:
    """Format bike availability as JSON."""
    primary_entries = [e for e in entries if e.is_primary]
    backup_entries = [e for e in entries if not e.is_primary]

    total_primary_ebikes = sum(e.total_ebikes for e in primary_entries)
    include_backups = total_primary_ebikes < LOW_AVAILABILITY_THRESHOLD

    entries_to_report = primary_entries + (backup_entries if include_backups else [])

    stations = []
    for entry in entries_to_report:
        if not entry.is_group:
            stations.append(
                {
                    "name": entry.name,
                    "ebikes": entry.total_ebikes,
                    "classic": entry.total_classic,
                    "primary": entry.is_primary,
                }
            )
        else:
            if entry.first_has_ebikes:
                stations.append(
                    {
                        "name": entry.name,
                        "ebikes": entry.total_ebikes,
                        "classic": entry.total_classic,
                        "primary": entry.is_primary,
                        "collapsed": True,
                    }
                )
            else:
                for station in entry.stations:
                    stations.append(
                        {
                            "name": f"{entry.name} {station.name}",
                            "ebikes": station.ebikes,
                            "classic": station.classic,
                            "primary": entry.is_primary,
                        }
                    )

    return {
        "type": "bikes",
        "total_primary_ebikes": total_primary_ebikes,
        "showing_backups": include_backups,
        "showing_classic": total_primary_ebikes < LOW_AVAILABILITY_THRESHOLD,
        "stations": stations,
    }


def _bad_request(message: str, content_type: str = "application/json"):
    """Return a 400 Bad Request response."""
    if content_type == "text/plain":
        return {
            "statusCode": 400,
            "headers": {"content-type": "text/plain"},
            "body": f"Error: {message}",
        }
    return {
        "statusCode": 400,
        "headers": {"content-type": "application/json"},
        "body": json.dumps({"error": message}),
    }


def citibike_check(event, context):
    """Returns JSON with station counts. Profile sent in POST body."""
    logger.info("citibike_check called")

    body = _get_body(event)
    profile = body.get("profile")
    if not profile:
        return _bad_request("Missing 'profile' in request body")

    count_type = _resolve_type(body)
    logger.info(f"Type: {count_type}, profile entries: {len(profile)}")

    try:
        station_data = _fetch_station_data(profile)
        entries = _process_profile(profile, station_data)

        if count_type == "docks":
            data = _format_docks_json(entries)
        else:
            data = _format_bikes_json(entries)

        logger.info(f"Response: {json.dumps(data)}")

    except Exception as e:
        logger.error(f"Error processing request: {e}", exc_info=True)
        return {
            "statusCode": 500,
            "headers": {"content-type": "application/json"},
            "body": json.dumps({"error": str(e)}),
        }

    return {
        "statusCode": 200,
        "headers": {
            "content-type": "application/json; charset=utf-8",
            "cache-control": "no-store",
        },
        "body": json.dumps(data),
    }


def citibike_check_english(event, context):
    """Returns English sentence describing station counts. Profile sent in POST body."""
    logger.info("citibike_check_english called")

    body = _get_body(event)
    profile = body.get("profile")
    if not profile:
        return _bad_request("Missing 'profile' in request body", "text/plain")

    count_type = _resolve_type(body)
    logger.info(f"Type: {count_type}, profile entries: {len(profile)}")

    try:
        station_data = _fetch_station_data(profile)
        entries = _process_profile(profile, station_data)

        if count_type == "docks":
            message = _format_docks_english(entries)
        else:
            message = _format_bikes_english(entries)

        logger.info(f"Response: {message}")

    except Exception as e:
        logger.error(f"Error processing request: {e}", exc_info=True)
        return {
            "statusCode": 500,
            "headers": {"content-type": "text/plain"},
            "body": f"Error: {e}",
        }

    return {
        "statusCode": 200,
        "headers": {
            "content-type": "text/plain; charset=utf-8",
            "cache-control": "no-store",
        },
        "body": message,
    }
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `uv run pytest tests/test_handler.py -v`

Expected: All tests pass.

- [ ] **Step 3: Commit**

```bash
git add src/lambda_app/handler.py
git commit -m "Refactor handler to stateless: accept profile in POST body, remove auth"
```

---

### Task 3: Delete Server-Side Config

**Files:**
- Delete: `src/lambda_app/config.py`
- Delete: `config.example.json`

- [ ] **Step 1: Delete config.py**

```bash
rm src/lambda_app/config.py
```

- [ ] **Step 2: Delete config.example.json**

```bash
rm config.example.json
```

- [ ] **Step 3: Verify tests still pass**

Run: `uv run pytest tests/test_handler.py -v`

Expected: All pass. The handler no longer imports from `config.py`.

- [ ] **Step 4: Commit**

```bash
git add -u
git commit -m "Delete config.py and config.example.json (no longer needed)"
```

---

### Task 4: Update Test Scripts

**Files:**
- Modify: `scripts/test_mock.py`
- Modify: `scripts/test_local.py`

- [ ] **Step 1: Rewrite test_mock.py for new handler interface**

Replace the full contents of `scripts/test_mock.py` with:

```python
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
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

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


TEST_PROFILE = [
    {
        "name": "43rd and Madison",
        "id": "station-43rd",
        "primary": True,
    },
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


def make_mock_summary(station_data: dict) -> MockParkingSummary:
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


def make_event(count_type: str) -> dict:
    body = {"profile": TEST_PROFILE, "type": count_type}
    return {"headers": {}, "body": json.dumps(body)}


def run_test(
    name: str,
    station_data: dict,
    count_type: str,
    expected_contains: list,
    verbose: bool = False,
):
    from lambda_app.handler import citibike_check, citibike_check_english

    mock_summary = make_mock_summary(station_data)
    with patch(
        "lambda_app.handler.compute_parking_summary", return_value=mock_summary
    ):
        event = make_event(count_type)
        response = citibike_check_english(event, None)
        body = response["body"]

        json_response = citibike_check(event, None)
        json_body = json.loads(json_response["body"])

        passed = all(exp in body for exp in expected_contains)
        status = "PASS" if passed else "FAIL"

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

    results.append(
        run_test(
            "Plenty of docks - primary only, collapsed",
            {
                "station-43rd": {"docks": 10},
                "station-gc-north": {"docks": 15},
                "station-gc-south": {"docks": 12},
                "station-40th-east": {"docks": 8},
                "station-40th-west": {"docks": 5},
            },
            "docks",
            ["10 at 43rd", "27 at grand central", "docks"],
            args.verbose,
        )
    )

    results.append(
        run_test(
            "GC north empty - should expand group",
            {
                "station-43rd": {"docks": 10},
                "station-gc-north": {"docks": 0},
                "station-gc-south": {"docks": 12},
                "station-40th-east": {"docks": 8},
                "station-40th-west": {"docks": 5},
            },
            "docks",
            ["10 at 43rd", "0 at grand central north", "12 at grand central south"],
            args.verbose,
        )
    )

    results.append(
        run_test(
            "Primary low (<=3) - should show backups",
            {
                "station-43rd": {"docks": 1},
                "station-gc-north": {"docks": 2},
                "station-gc-south": {"docks": 0},
                "station-40th-east": {"docks": 8},
                "station-40th-west": {"docks": 5},
            },
            "docks",
            ["1 at 43rd", "2 at grand central", "13 at 40th"],
            args.verbose,
        )
    )

    results.append(
        run_test(
            "Primary empty - should show backups",
            {
                "station-43rd": {"docks": 0},
                "station-gc-north": {"docks": 0},
                "station-gc-south": {"docks": 0},
                "station-40th-east": {"docks": 8},
                "station-40th-west": {"docks": 5},
            },
            "docks",
            ["0 at 43rd", "0 at grand central", "13 at 40th"],
            args.verbose,
        )
    )

    results.append(
        run_test(
            "Everything empty",
            {
                "station-43rd": {"docks": 0},
                "station-gc-north": {"docks": 0},
                "station-gc-south": {"docks": 0},
                "station-40th-east": {"docks": 0},
                "station-40th-west": {"docks": 0},
            },
            "docks",
            ["0 at 43rd", "0 at grand central", "0 at 40th"],
            args.verbose,
        )
    )

    print()
    print("=" * 60)
    print("BIKES TESTS")
    print("=" * 60)

    results.append(
        run_test(
            "Plenty of ebikes - ebikes only, collapsed",
            {
                "station-43rd": {"ebikes": 5, "classic": 3},
                "station-gc-north": {"ebikes": 8, "classic": 10},
                "station-gc-south": {"ebikes": 4, "classic": 6},
                "station-40th-east": {"ebikes": 3, "classic": 5},
                "station-40th-west": {"ebikes": 2, "classic": 4},
            },
            "bikes",
            ["5 ebikes at 43rd", "12 ebikes at grand central"],
            args.verbose,
        )
    )

    results.append(
        run_test(
            "GC north no ebikes - should expand group",
            {
                "station-43rd": {"ebikes": 5, "classic": 3},
                "station-gc-north": {"ebikes": 0, "classic": 10},
                "station-gc-south": {"ebikes": 4, "classic": 6},
                "station-40th-east": {"ebikes": 3, "classic": 5},
                "station-40th-west": {"ebikes": 2, "classic": 4},
            },
            "bikes",
            [
                "5 ebikes at 43rd",
                "0 ebikes at grand central north",
                "4 ebikes at grand central south",
            ],
            args.verbose,
        )
    )

    results.append(
        run_test(
            "Low ebikes (<3) - should show classic and backups",
            {
                "station-43rd": {"ebikes": 1, "classic": 5},
                "station-gc-north": {"ebikes": 1, "classic": 10},
                "station-gc-south": {"ebikes": 0, "classic": 6},
                "station-40th-east": {"ebikes": 3, "classic": 5},
                "station-40th-west": {"ebikes": 2, "classic": 4},
            },
            "bikes",
            ["1 ebikes at 43rd", "1 ebikes at grand central", "classic", "40th"],
            args.verbose,
        )
    )

    results.append(
        run_test(
            "No ebikes - should show classic",
            {
                "station-43rd": {"ebikes": 0, "classic": 5},
                "station-gc-north": {"ebikes": 0, "classic": 10},
                "station-gc-south": {"ebikes": 0, "classic": 6},
                "station-40th-east": {"ebikes": 0, "classic": 5},
                "station-40th-west": {"ebikes": 0, "classic": 4},
            },
            "bikes",
            ["0 ebikes at 43rd", "0 ebikes at grand central", "classic"],
            args.verbose,
        )
    )

    print()
    print("=" * 60)
    passed = sum(results)
    total = len(results)
    print(f"Results: {passed}/{total} tests passed")

    if passed < total:
        sys.exit(1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run test_mock.py**

Run: `uv run scripts/test_mock.py -v`

Expected: All 9 tests pass.

- [ ] **Step 3: Rewrite test_local.py for new handler interface**

Replace the full contents of `scripts/test_local.py` with:

```python
#!/usr/bin/env python3
"""
Test the Lambda handlers locally against real Citibike data.

Usage:
    uv run scripts/test_local.py
    uv run scripts/test_local.py --type bikes
    uv run scripts/test_local.py --profile home
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from lambda_app.handler import citibike_check, citibike_check_english


def make_event(profile: list, q: str = None, count_type: str = None) -> dict:
    body = {"profile": profile}
    if q:
        body["q"] = q
    if count_type:
        body["type"] = count_type
    return {"headers": {}, "body": json.dumps(body)}


def main():
    parser = argparse.ArgumentParser(description="Test Lambda handlers locally")
    parser.add_argument(
        "--profile-file",
        default="josh-profiles.json",
        help="Path to profiles JSON file",
    )
    parser.add_argument("--profile", default="work", help="Profile name")
    parser.add_argument(
        "--type", default="docks", choices=["docks", "bikes"], help="Type"
    )
    parser.add_argument("--q", default=None, help="Natural language query")
    parser.add_argument("--json", action="store_true", help="Use JSON endpoint")
    args = parser.parse_args()

    profiles_path = Path(args.profile_file)
    if not profiles_path.exists():
        print(f"Error: {args.profile_file} not found")
        print("Create it from josh-profiles.json or build one with the station picker.")
        sys.exit(1)

    with open(profiles_path) as f:
        profiles = json.load(f)

    profile = profiles.get(args.profile)
    if not profile:
        print(f"Error: Profile '{args.profile}' not found")
        print(f"Available profiles: {list(profiles.keys())}")
        sys.exit(1)

    event = make_event(profile, q=args.q, count_type=args.type)

    print(f"Profile: {args.profile} ({len(profile)} entries)")
    print(f"Type: {args.type}")
    print("-" * 50)

    if args.json:
        response = citibike_check(event, None)
    else:
        response = citibike_check_english(event, None)

    print(f"Status: {response['statusCode']}")
    print()

    if response["statusCode"] == 200:
        if args.json:
            data = json.loads(response["body"])
            print(json.dumps(data, indent=2))
        else:
            print("Response:")
            print(response["body"])
    else:
        print("Error:")
        print(response["body"])


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Commit**

```bash
git add scripts/test_mock.py scripts/test_local.py
git commit -m "Update test scripts for stateless handler interface"
```

---

### Task 5: Update Infrastructure

**Files:**
- Modify: `template.yaml`
- Modify: `deploy.sh`
- Modify: `.gitignore`

- [ ] **Step 1: Update template.yaml**

Change the `/citibike-check` endpoint from GET to POST. In `template.yaml`, find the `CitibikeCheckFunction` Events section and change `Method: GET` to `Method: POST`. Also rename the event key for clarity:

Replace:

```yaml
      Events:
        GetCitibikeCheck:
          Type: Api
          Properties:
            RestApiId: !Ref CitibikeApi
            Path: /citibike-check
            Method: GET
```

With:

```yaml
      Events:
        PostCitibikeCheck:
          Type: Api
          Properties:
            RestApiId: !Ref CitibikeApi
            Path: /citibike-check
            Method: POST
```

- [ ] **Step 2: Update deploy.sh**

Replace the full contents of `deploy.sh` with:

```bash
#!/usr/bin/env bash
set -euo pipefail

STACK_NAME="${STACK_NAME:-citibike-checker}"
REGION="${AWS_REGION:-us-east-1}"

sam build --use-container
sam deploy \
  --stack-name "$STACK_NAME" \
  --region "$REGION" \
  --capabilities CAPABILITY_IAM \
  --resolve-s3 \
  --no-confirm-changeset

API_URL="$(aws cloudformation describe-stacks --region "$REGION" --stack-name "$STACK_NAME" --query "Stacks[0].Outputs[?OutputKey=='ApiBaseUrl'].OutputValue" --output text)"

echo ""
echo "=========================================="
echo "Deployment complete!"
echo "=========================================="
echo "Endpoint: $API_URL"
echo ""
echo "Test with:"
echo "curl -sS \"$API_URL/citibike-check-english\" -X POST -H 'Content-Type: application/json' -d '{\"q\": \"docks\", \"profile\": [{\"name\": \"test\", \"id\": \"STATION_ID\", \"primary\": true}]}'"
```

- [ ] **Step 3: Update .gitignore**

In `.gitignore`, update the user config section. Replace:

```
# User config (keep config.example.json)
config.json
src/config.json
josh-profiles.json
```

With:

```
# User config
josh-profiles.json
```

The `config.json` and `src/config.json` lines are no longer needed since those files and the system that used them are gone.

- [ ] **Step 4: Commit**

```bash
git add template.yaml deploy.sh .gitignore
git commit -m "Update infrastructure: both endpoints POST, simplify deploy"
```

---

### Task 6: Build Slim Stations Data for Web App

**Files:**
- Create: `scripts/build_stations_web.py`
- Create: `docs/stations.json`
- Modify: `scripts/refresh_stations.sh`

- [ ] **Step 1: Create build script**

Create `scripts/build_stations_web.py`:

```python
#!/usr/bin/env python3
"""Build a slim stations.json for the web app from the full data/stations.json."""

import json
from pathlib import Path

DATA_PATH = Path(__file__).parent.parent / "data" / "stations.json"
OUT_PATH = Path(__file__).parent.parent / "docs" / "stations.json"


def main():
    with open(DATA_PATH) as f:
        stations = json.load(f)

    slim = [
        {
            "name": s["name"],
            "id": s["station_id"],
            "lat": s["lat"],
            "lon": s["lon"],
        }
        for s in stations
    ]

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w") as f:
        json.dump(slim, f, separators=(",", ":"))

    size_kb = OUT_PATH.stat().st_size / 1024
    print(f"Wrote {len(slim)} stations to {OUT_PATH} ({size_kb:.0f} KB)")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the build script**

Run: `python3 scripts/build_stations_web.py`

Expected: Output like "Wrote 2321 stations to docs/stations.json (220 KB)"

- [ ] **Step 3: Update refresh_stations.sh to also build web data**

Append to the end of `scripts/refresh_stations.sh`:

```bash

# Also build the slim version for the web app
echo "Building slim stations.json for web app..."
python3 "$(dirname "$0")/build_stations_web.py"
```

- [ ] **Step 4: Commit**

```bash
git add scripts/build_stations_web.py docs/stations.json scripts/refresh_stations.sh
git commit -m "Add slim stations.json for web app, update refresh script"
```

---

### Task 7: Build Station Picker Web App

**Files:**
- Create: `docs/index.html`

- [ ] **Step 1: Create the station picker web app**

Create `docs/index.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Citi Bike Station Picker</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.css">
<link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.Default.css">
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #f5f5f5; color: #333; }

header { background: #0057b8; color: #fff; padding: 12px 20px; }
header h1 { font-size: 1.2rem; font-weight: 600; }
header p { font-size: 0.85rem; opacity: 0.85; margin-top: 2px; }

#search-container { display: flex; gap: 8px; padding: 10px 20px; background: #fff; border-bottom: 1px solid #ddd; flex-wrap: wrap; }
#address-input { flex: 1; min-width: 200px; padding: 8px 12px; border: 1px solid #ccc; border-radius: 4px; font-size: 14px; }
#search-container button { padding: 8px 16px; border: none; border-radius: 4px; font-size: 14px; cursor: pointer; white-space: nowrap; }
#search-btn { background: #0057b8; color: #fff; }
#locate-btn { background: #e8e8e8; color: #333; }
#search-container button:hover { opacity: 0.85; }

#content { display: flex; height: calc(100vh - 110px); }
#map { flex: 1; min-width: 0; }

#sidebar { width: 380px; background: #fff; border-left: 1px solid #ddd; overflow-y: auto; display: flex; flex-direction: column; }
#sidebar h2 { padding: 12px 16px 8px; font-size: 1rem; border-bottom: 1px solid #eee; }

#station-list { flex: 1; overflow-y: auto; padding: 8px; }
.station-entry { background: #f9f9f9; border: 1px solid #e0e0e0; border-radius: 6px; padding: 10px 12px; margin-bottom: 6px; }
.station-entry.is-group { border-left: 3px solid #0057b8; }
.station-header { display: flex; align-items: center; gap: 8px; }
.station-header input[type="text"] { flex: 1; border: 1px solid #ddd; border-radius: 3px; padding: 4px 8px; font-size: 13px; }
.station-header label { font-size: 12px; white-space: nowrap; display: flex; align-items: center; gap: 3px; }
.station-header button { background: none; border: none; cursor: pointer; font-size: 16px; color: #999; padding: 2px; }
.station-header button:hover { color: #e00; }
.group-members { margin-top: 6px; padding-left: 12px; font-size: 12px; color: #666; }
.group-members div { padding: 2px 0; }

#actions { padding: 12px 16px; border-top: 1px solid #eee; display: flex; gap: 8px; flex-wrap: wrap; }
#actions button { padding: 8px 14px; border: none; border-radius: 4px; font-size: 13px; cursor: pointer; }
#group-btn { background: #e8e8e8; color: #333; }
#generate-btn { background: #0057b8; color: #fff; flex: 1; }
#actions button:hover { opacity: 0.85; }
#actions button:disabled { opacity: 0.4; cursor: default; }

#output { padding: 16px; border-top: 1px solid #eee; }
#output h3 { font-size: 0.9rem; margin: 12px 0 6px; }
#output h3:first-child { margin-top: 0; }
#output pre { background: #f0f0f0; padding: 10px; border-radius: 4px; font-size: 12px; overflow-x: auto; white-space: pre-wrap; word-break: break-all; position: relative; }
.copy-btn { position: absolute; top: 6px; right: 6px; background: #0057b8; color: #fff; border: none; border-radius: 3px; padding: 4px 10px; font-size: 11px; cursor: pointer; }
.copy-btn:hover { opacity: 0.85; }
.pre-wrapper { position: relative; }
#instructions { font-size: 13px; line-height: 1.6; }
#instructions ol { padding-left: 20px; }
#instructions li { margin-bottom: 6px; }
#instructions code { background: #f0f0f0; padding: 2px 6px; border-radius: 3px; font-size: 12px; }

@media (max-width: 768px) {
  #content { flex-direction: column; height: auto; }
  #map { height: 50vh; }
  #sidebar { width: 100%; max-height: 50vh; }
}
</style>
</head>
<body>

<header>
  <h1>Citi Bike Station Picker</h1>
  <p>Pick stations, generate a config, set up your Siri Shortcut</p>
</header>

<div id="search-container">
  <input type="text" id="address-input" placeholder="Search for an address or intersection...">
  <button id="search-btn">Search</button>
  <button id="locate-btn">My Location</button>
</div>

<div id="content">
  <div id="map"></div>
  <div id="sidebar">
    <h2>Selected Stations <span id="station-count">(0)</span></h2>
    <div id="station-list">
      <p style="padding:16px;color:#999;font-size:13px;">Click stations on the map to add them here.</p>
    </div>
    <div id="actions">
      <button id="group-btn" disabled>Group Checked</button>
      <button id="generate-btn" disabled>Generate Config</button>
    </div>
    <div id="output" style="display:none;"></div>
  </div>
</div>

<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="https://unpkg.com/leaflet.markercluster@1.5.3/dist/leaflet.markercluster.js"></script>
<script>
(function() {
  // ===== Configuration =====
  const API_URL = 'https://YOUR_API_URL/prod';  // Replace with your Lambda API URL

  // ===== State =====
  let allStations = [];       // Raw station data from stations.json
  let selected = [];          // Array of {id, name, displayName, lat, lon, primary, groupId}
  let groups = {};            // groupId -> {name, stationIds}
  let nextGroupId = 1;
  let markerMap = {};         // stationId -> Leaflet marker

  // ===== Map Setup =====
  const map = L.map('map').setView([40.7580, -73.9785], 14);  // Midtown Manhattan
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; OpenStreetMap contributors',
    maxZoom: 19
  }).addTo(map);

  const clusterGroup = L.markerClusterGroup({
    maxClusterRadius: 40,
    spiderfyOnMaxZoom: true,
    disableClusteringAtZoom: 16
  });
  map.addLayer(clusterGroup);

  const defaultIcon = L.divIcon({ className: 'station-marker', html: '<div style="width:10px;height:10px;background:#0057b8;border:2px solid #fff;border-radius:50%;box-shadow:0 1px 3px rgba(0,0,0,.3);"></div>', iconSize: [14, 14], iconAnchor: [7, 7] });
  const selectedIcon = L.divIcon({ className: 'station-marker', html: '<div style="width:12px;height:12px;background:#2ecc40;border:2px solid #fff;border-radius:50%;box-shadow:0 1px 3px rgba(0,0,0,.3);"></div>', iconSize: [16, 16], iconAnchor: [8, 8] });

  // ===== Load Stations =====
  fetch('stations.json')
    .then(r => r.json())
    .then(stations => {
      allStations = stations;
      stations.forEach(s => {
        const marker = L.marker([s.lat, s.lon], { icon: defaultIcon });
        marker.stationData = s;
        marker.bindPopup(() => {
          const isSelected = selected.some(sel => sel.id === s.id);
          const btn = isSelected ? `<button onclick="window._removeStation('${s.id}')">Remove</button>` : `<button onclick="window._addStation('${s.id}')">Add to Profile</button>`;
          return `<b>${s.name}</b><br><small>${s.id}</small><br>${btn}`;
        });
        markerMap[s.id] = marker;
        clusterGroup.addLayer(marker);
      });
    });

  // ===== Geolocation =====
  document.getElementById('locate-btn').addEventListener('click', () => {
    if (!navigator.geolocation) return alert('Geolocation not supported by your browser.');
    navigator.geolocation.getCurrentPosition(
      pos => map.setView([pos.coords.latitude, pos.coords.longitude], 16),
      () => alert('Could not get your location.')
    );
  });

  // ===== Address Search =====
  function searchAddress() {
    const q = document.getElementById('address-input').value.trim();
    if (!q) return;
    fetch(`https://nominatim.openstreetmap.org/search?format=json&q=${encodeURIComponent(q)}&limit=1`, {
      headers: { 'User-Agent': 'CitiBikeStationPicker/1.0' }
    })
      .then(r => r.json())
      .then(results => {
        if (results.length === 0) return alert('Address not found.');
        map.setView([parseFloat(results[0].lat), parseFloat(results[0].lon)], 16);
      });
  }
  document.getElementById('search-btn').addEventListener('click', searchAddress);
  document.getElementById('address-input').addEventListener('keydown', e => { if (e.key === 'Enter') searchAddress(); });

  // ===== Station Selection =====
  window._addStation = function(id) {
    if (selected.some(s => s.id === id)) return;
    const station = allStations.find(s => s.id === id);
    if (!station) return;
    selected.push({
      id: station.id,
      name: station.name,
      displayName: station.name,
      lat: station.lat,
      lon: station.lon,
      primary: selected.length < 2,  // First two default to primary
      groupId: null
    });
    if (markerMap[id]) markerMap[id].setIcon(selectedIcon);
    map.closePopup();
    renderPanel();
  };

  window._removeStation = function(id) {
    // If in a group, remove from group
    const entry = selected.find(s => s.id === id);
    if (entry && entry.groupId) {
      const group = groups[entry.groupId];
      if (group) {
        group.stationIds = group.stationIds.filter(sid => sid !== id);
        if (group.stationIds.length < 2) {
          // Dissolve group if less than 2 members
          group.stationIds.forEach(sid => {
            const s = selected.find(sel => sel.id === sid);
            if (s) s.groupId = null;
          });
          delete groups[entry.groupId];
        }
      }
    }
    selected = selected.filter(s => s.id !== id);
    if (markerMap[id]) markerMap[id].setIcon(defaultIcon);
    map.closePopup();
    renderPanel();
  };

  // ===== Render Panel =====
  function renderPanel() {
    const listEl = document.getElementById('station-list');
    const countEl = document.getElementById('station-count');
    const generateBtn = document.getElementById('generate-btn');
    const groupBtn = document.getElementById('group-btn');

    countEl.textContent = `(${selected.length})`;
    generateBtn.disabled = selected.length === 0;

    if (selected.length === 0) {
      listEl.innerHTML = '<p style="padding:16px;color:#999;font-size:13px;">Click stations on the map to add them here.</p>';
      document.getElementById('output').style.display = 'none';
      groupBtn.disabled = true;
      return;
    }

    // Collect grouped and ungrouped
    const rendered = new Set();
    let html = '';

    // Render groups first
    Object.entries(groups).forEach(([gid, group]) => {
      const members = selected.filter(s => s.groupId === gid);
      if (members.length === 0) return;
      members.forEach(m => rendered.add(m.id));

      html += `<div class="station-entry is-group">
        <div class="station-header">
          <input type="checkbox" data-group-check="${gid}">
          <input type="text" value="${escHtml(group.name)}" onchange="window._renameGroup('${gid}', this.value)">
          <label><input type="checkbox" ${members[0].primary ? 'checked' : ''} onchange="window._toggleGroupPrimary('${gid}', this.checked)"> Primary</label>
          <button onclick="window._dissolveGroup('${gid}')" title="Ungroup">&times;</button>
        </div>
        <div class="group-members">${members.map(m => `<div>${escHtml(m.name)} <button onclick="window._removeStation('${m.id}')" style="background:none;border:none;color:#999;cursor:pointer;font-size:12px;">&times;</button></div>`).join('')}</div>
      </div>`;
    });

    // Render ungrouped
    selected.filter(s => !rendered.has(s.id)).forEach(s => {
      html += `<div class="station-entry">
        <div class="station-header">
          <input type="checkbox" data-station-check="${s.id}">
          <input type="text" value="${escHtml(s.displayName)}" onchange="window._rename('${s.id}', this.value)">
          <label><input type="checkbox" ${s.primary ? 'checked' : ''} onchange="window._togglePrimary('${s.id}', this.checked)"> Primary</label>
          <button onclick="window._removeStation('${s.id}')" title="Remove">&times;</button>
        </div>
      </div>`;
    });

    listEl.innerHTML = html;
    updateGroupBtn();
  }

  function escHtml(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }

  function updateGroupBtn() {
    const checks = document.querySelectorAll('[data-station-check]:checked');
    document.getElementById('group-btn').disabled = checks.length < 2;
  }
  document.getElementById('station-list').addEventListener('change', e => {
    if (e.target.matches('[data-station-check]')) updateGroupBtn();
  });

  // ===== Rename / Primary =====
  window._rename = function(id, name) {
    const s = selected.find(sel => sel.id === id);
    if (s) s.displayName = name;
  };
  window._togglePrimary = function(id, checked) {
    const s = selected.find(sel => sel.id === id);
    if (s) s.primary = checked;
  };
  window._renameGroup = function(gid, name) {
    if (groups[gid]) groups[gid].name = name;
  };
  window._toggleGroupPrimary = function(gid, checked) {
    selected.filter(s => s.groupId === gid).forEach(s => s.primary = checked);
    renderPanel();
  };

  // ===== Grouping =====
  document.getElementById('group-btn').addEventListener('click', () => {
    const checks = document.querySelectorAll('[data-station-check]:checked');
    const ids = Array.from(checks).map(c => c.dataset.stationCheck);
    if (ids.length < 2) return;

    const gid = 'g' + (nextGroupId++);
    const members = ids.map(id => selected.find(s => s.id === id)).filter(Boolean);
    const groupName = prompt('Group name:', members[0].displayName);
    if (!groupName) return;

    groups[gid] = { name: groupName, stationIds: ids };
    members.forEach(m => { m.groupId = gid; });
    renderPanel();
  });

  window._dissolveGroup = function(gid) {
    selected.filter(s => s.groupId === gid).forEach(s => { s.groupId = null; });
    delete groups[gid];
    renderPanel();
  };

  // ===== Generate Config =====
  document.getElementById('generate-btn').addEventListener('click', () => {
    const profile = buildProfile();
    const docksJson = JSON.stringify({ q: 'docks', profile }, null, 2);
    const bikesJson = JSON.stringify({ q: 'bikes', profile }, null, 2);

    const outputEl = document.getElementById('output');
    outputEl.style.display = 'block';
    outputEl.innerHTML = `
      <h3>Docks Config</h3>
      <div class="pre-wrapper"><pre id="docks-json">${escHtml(docksJson)}</pre><button class="copy-btn" onclick="window._copy('docks-json')">Copy</button></div>

      <h3>Bikes Config</h3>
      <div class="pre-wrapper"><pre id="bikes-json">${escHtml(bikesJson)}</pre><button class="copy-btn" onclick="window._copy('bikes-json')">Copy</button></div>

      <h3>Siri Shortcut Setup</h3>
      <div id="instructions">
        <p>Create one Shortcut per config (e.g., "Citi bike work docks" and "Citi bike work bikes"):</p>
        <ol>
          <li>Open the <b>Shortcuts</b> app, tap <b>+</b></li>
          <li>Name it (e.g., "Citi bike work docks")</li>
          <li>Add action: <b>Get Contents of URL</b>
            <ul>
              <li>URL: <code>${API_URL}/citibike-check-english</code></li>
              <li>Method: <b>POST</b></li>
              <li>Headers: add <code>Content-Type</code> = <code>application/json</code></li>
              <li>Request Body: <b>JSON</b> &mdash; paste the config from above</li>
            </ul>
          </li>
          <li>Add action: <b>Speak Text</b> &mdash; speak the result from the previous step</li>
          <li>Done! Trigger with "Hey Siri, Citi bike work docks"</li>
        </ol>
        <p style="margin-top:12px;color:#666;font-size:12px;">Repeat for each profile/type combo you want (work docks, work bikes, home docks, etc.).</p>
      </div>
    `;
    outputEl.scrollIntoView({ behavior: 'smooth' });
  });

  function buildProfile() {
    const profile = [];
    const rendered = new Set();

    // Groups first
    Object.entries(groups).forEach(([gid, group]) => {
      const members = selected.filter(s => s.groupId === gid);
      if (members.length === 0) return;
      members.forEach(m => rendered.add(m.id));

      const entry = {
        name: group.name,
        stations: members.map(m => ({ id: m.id, name: m.displayName }))
      };
      if (members[0].primary) entry.primary = true;
      profile.push(entry);
    });

    // Ungrouped stations
    selected.filter(s => !rendered.has(s.id)).forEach(s => {
      const entry = { name: s.displayName, id: s.id };
      if (s.primary) entry.primary = true;
      profile.push(entry);
    });

    return profile;
  }

  window._copy = function(elId) {
    const text = document.getElementById(elId).textContent;
    navigator.clipboard.writeText(text).then(() => {
      const btn = document.querySelector(`[onclick="window._copy('${elId}')"]`);
      const orig = btn.textContent;
      btn.textContent = 'Copied!';
      setTimeout(() => btn.textContent = orig, 1500);
    });
  };
})();
</script>
</body>
</html>
```

- [ ] **Step 2: Test the web app locally**

Run: `python3 -m http.server 8000 -d docs`

Open `http://localhost:8000` in a browser. Verify:
- Map loads centered on Midtown Manhattan
- Station markers appear (may take a moment for clustering)
- Search box recenters the map on a typed address
- "My Location" button recenters on current location (if allowed)
- Clicking a station marker shows a popup with "Add to Profile"
- Adding stations populates the sidebar
- Primary checkbox, rename, remove all work
- Grouping two stations works (select checkboxes, click "Group Checked", enter name)
- "Generate Config" produces valid JSON for both docks and bikes
- Copy buttons work
- Instructions section shows correctly

Stop the server with Ctrl+C.

- [ ] **Step 3: Commit**

```bash
git add docs/index.html
git commit -m "Add station picker web app for generating Shortcut configs"
```

---

### Task 8: Update README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Rewrite README.md**

Replace the full contents of `README.md` with:

````markdown
# citibike-checker

Check Citi Bike dock and bike availability with smart priority-based reporting. Designed for Siri Shortcuts — ask "Hey Siri, Citi bike work docks" and hear availability at your configured stations.

## How It Works

1. **Pick your stations** using the [Station Picker](https://joshlebed.github.io/citibike-checker/) web app
2. **Generate a config** — the picker builds a JSON payload with your selected stations
3. **Create a Siri Shortcut** that POSTs your config to the API and speaks the result

The server is stateless — your station config lives in each Shortcut, not on the server. Create multiple Shortcuts for different locations (work, home, etc.).

## Quick Start (For Users)

1. Visit the [Station Picker](https://joshlebed.github.io/citibike-checker/)
2. Find your stations on the map (search by address or use your location)
3. Click stations to select them, mark your closest as "primary"
4. Click "Generate Config" and follow the Siri Shortcut instructions

## API Endpoints

### `POST /citibike-check-english` (Plain text for Siri)

Returns a human-readable sentence.

```bash
curl -sS "https://YOUR_API_URL/prod/citibike-check-english" \
  -X POST \
  -H "Content-Type: application/json" \
  -d '{
    "q": "docks",
    "profile": [
      {"name": "43rd and Madison", "id": "2af3ecc3-4f43-468a-a7cc-bb4804ee3e7a", "primary": true},
      {"name": "grand central", "primary": true, "stations": [
        {"id": "66dc8025-0aca-11e7-82f6-3863bb44ef7c", "name": "north"},
        {"id": "66dc7f02-0aca-11e7-82f6-3863bb44ef7c", "name": "south"}
      ]}
    ]
  }'
# Output: 10 docks at 43rd and Madison, 27 docks at grand central
```

### `POST /citibike-check` (JSON)

Returns structured JSON with station data. Same request format.

### Request Format

```json
{
  "q": "docks",
  "profile": [
    {
      "name": "station display name",
      "id": "station-uuid",
      "primary": true
    },
    {
      "name": "group name",
      "primary": true,
      "stations": [
        { "id": "station-uuid-1", "name": "sub-name" },
        { "id": "station-uuid-2", "name": "sub-name" }
      ]
    }
  ]
}
```

- `q`: `"docks"` or `"bikes"` (defaults to `"docks"`)
- `type`: explicit override for `q`
- `profile`: array of station entries (single stations or groups)
- `primary: true`: always reported. Non-primary entries only shown when primary availability is low.

### Smart Reporting Logic

**Docks:**
- Primary entries always shown
- If primary total ≤3 docks, backup entries also shown
- Groups collapse to total if first station has availability; expand if first is empty

**Bikes:**
- E-bikes prioritized over classic bikes
- If primary e-bikes <3, also report classic bikes and backup stations

## Deploy Your Own

Prerequisites: AWS SAM CLI, Docker, AWS credentials.

```bash
# Build and deploy the Lambda
./deploy.sh
```

The station picker web app is in `docs/` and can be hosted on GitHub Pages or any static hosting.

## Development

```bash
uv sync

# Run tests
uv run pytest tests/ -v
uv run scripts/test_mock.py -v

# Test locally against real data (requires josh-profiles.json or similar)
uv run scripts/test_local.py --profile work --type docks

# Refresh station data
./scripts/refresh_stations.sh
```

## Finding Station IDs

Use the [Station Picker](https://joshlebed.github.io/citibike-checker/) web app, or search locally:

```bash
grep -i "42 st" data/stations.json
jq '.[] | select(.name | test("42 St"; "i")) | {name, station_id}' data/stations.json
```
````

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "Rewrite README for stateless API and station picker setup flow"
```

---

### Task 9: Final Cleanup

- [ ] **Step 1: Verify everything works end-to-end**

Run all tests:
```bash
uv run pytest tests/test_handler.py -v
uv run scripts/test_mock.py -v
```

Expected: All pass.

Verify web app:
```bash
python3 -m http.server 8000 -d docs
```
Open `http://localhost:8000`, pick a couple stations, generate config, verify the JSON looks correct.

- [ ] **Step 2: Verify no stale references**

Check for any remaining references to the old config system:

```bash
grep -r "config\.json" --include="*.py" --include="*.sh" --include="*.yaml" --include="*.md" .
grep -r "api_key\|api-key\|X-API-Key" --include="*.py" --include="*.yaml" .
grep -r "get_user_by_api_key\|get_config\|_find_config" --include="*.py" .
```

Expected: No results from `src/` or `scripts/` (README may mention API key in the context of HTTP headers, which is fine since the request body now does the work). The `template.yaml` should not reference API keys. `deploy.sh` should not reference `config.json`.

- [ ] **Step 3: Final commit if any cleanup needed**

If any stale references were found and fixed:
```bash
git add -A
git commit -m "Clean up remaining references to old config system"
```
