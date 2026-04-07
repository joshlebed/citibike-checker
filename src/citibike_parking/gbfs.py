from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests


DEFAULT_STATUS_URL = "https://gbfs.citibikenyc.com/gbfs/en/station_status.json"
DEFAULT_INFO_URL = "https://gbfs.citibikenyc.com/gbfs/en/station_information.json"

# Module-level TTL cache for GBFS feed fetches. Warm Lambda containers reuse
# the cached feeds across invocations, which collapses multiple simultaneous
# requests into one upstream HTTP call per URL every FEED_CACHE_TTL_S seconds.
# The GBFS feeds update roughly every 10 seconds, so a 5s TTL keeps data fresh
# while cutting upstream load ~10-25x at steady state.
FEED_CACHE_TTL_S = 5.0
_feed_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}


@dataclass(frozen=True)
class StationResult:
    station_id: str
    name: Optional[str]
    docks_available: int
    bikes_available: int
    ebikes_available: int
    classic_bikes_available: int
    is_installed: Optional[bool]
    is_renting: Optional[bool]
    is_returning: Optional[bool]


@dataclass(frozen=True)
class ParkingSummary:
    station_ids: List[str]
    available_spots: int
    stations: List[StationResult]
    as_of: str  # ISO-8601 UTC
    ttl_seconds: Optional[int]


class GbfsError(RuntimeError):
    pass


def _fetch_json(url: str, timeout_s: float = 10.0) -> Dict[str, Any]:
    try:
        resp = requests.get(url, timeout=timeout_s, headers={"Accept": "application/json"})
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        raise GbfsError(f"Failed to fetch/parse GBFS feed: {url} ({e})") from e


def _fetch_json_cached(url: str, timeout_s: float = 10.0) -> Dict[str, Any]:
    """
    TTL-cached wrapper around _fetch_json. Cache lives in module-level state
    and survives across invocations within a warm Lambda container.
    """
    now = time.monotonic()
    cached = _feed_cache.get(url)
    if cached is not None and (now - cached[0]) < FEED_CACHE_TTL_S:
        return cached[1]
    data = _fetch_json(url, timeout_s=timeout_s)
    _feed_cache[url] = (now, data)
    return data


def _parse_station_status(payload: Dict[str, Any]) -> Tuple[Dict[str, Dict[str, Any]], Optional[int]]:
    """
    Returns (station_id -> station_status_obj, ttl_seconds)
    """
    try:
        ttl = payload.get("ttl")
        stations = payload["data"]["stations"]
        by_id = {s["station_id"]: s for s in stations}
        return by_id, ttl
    except Exception as e:
        raise GbfsError(f"Unexpected station_status schema: {e}") from e


def _parse_station_information(payload: Dict[str, Any]) -> Dict[str, str]:
    """
    Returns station_id -> station_name
    """
    try:
        stations = payload["data"]["stations"]
        return {s["station_id"]: s.get("name", "") for s in stations}
    except Exception as e:
        raise GbfsError(f"Unexpected station_information schema: {e}") from e


def compute_parking_summary(
    station_ids: Iterable[str],
    *,
    station_status_url: str = DEFAULT_STATUS_URL,
    station_information_url: Optional[str] = DEFAULT_INFO_URL,
    timeout_s: float = 10.0,
) -> ParkingSummary:
    station_ids_list = [s.strip() for s in station_ids if s and s.strip()]
    if not station_ids_list:
        raise ValueError("No station_ids provided")

    status_payload = _fetch_json_cached(station_status_url, timeout_s=timeout_s)
    status_by_id, ttl = _parse_station_status(status_payload)

    name_by_id: Dict[str, str] = {}
    if station_information_url:
        info_payload = _fetch_json_cached(station_information_url, timeout_s=timeout_s)
        name_by_id = _parse_station_information(info_payload)

    results: List[StationResult] = []
    missing: List[str] = []

    for sid in station_ids_list:
        st = status_by_id.get(sid)
        if not st:
            missing.append(sid)
            continue

        bikes_available = int(st.get("num_bikes_available", 0) or 0)
        ebikes_available = int(st.get("num_ebikes_available", 0) or 0)
        classic_bikes_available = max(0, bikes_available - ebikes_available)

        results.append(
            StationResult(
                station_id=sid,
                name=name_by_id.get(sid) if name_by_id else None,
                docks_available=int(st.get("num_docks_available", 0) or 0),
                bikes_available=bikes_available,
                ebikes_available=ebikes_available,
                classic_bikes_available=classic_bikes_available,
                is_installed=st.get("is_installed"),
                is_renting=st.get("is_renting"),
                is_returning=st.get("is_returning"),
            )
        )

    if missing:
        # Hard fail locally so you catch typos early.
        # In Lambda you might choose to "soft fail" and return partial results.
        raise GbfsError(f"Station IDs not found in station_status feed: {missing}")

    available_spots = sum(r.docks_available for r in results)
    as_of = datetime.now(timezone.utc).isoformat()

    return ParkingSummary(
        station_ids=station_ids_list,
        available_spots=available_spots,
        stations=results,
        as_of=as_of,
        ttl_seconds=ttl if isinstance(ttl, int) else None,
    )


def summary_as_dict(summary: ParkingSummary) -> Dict[str, Any]:
    return {
        "available_spots": summary.available_spots,
        "station_ids": summary.station_ids,
        "stations": [
            {
                "station_id": s.station_id,
                "name": s.name,
                "docks_available": s.docks_available,
                "bikes_available": s.bikes_available,
                "is_installed": s.is_installed,
                "is_renting": s.is_renting,
                "is_returning": s.is_returning,
            }
            for s in summary.stations
        ],
        "as_of": summary.as_of,
        "ttl_seconds": summary.ttl_seconds,
    }
