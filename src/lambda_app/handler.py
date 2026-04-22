import json
import logging
import os
from dataclasses import dataclass

from citibike_parking.gbfs import compute_parking_summary

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)


# Threshold: if primary availability is at or below this, also show backups
LOW_AVAILABILITY_THRESHOLD = 3

# Defensive limits on incoming profile size to bound CPU/memory and protect
# upstream GBFS feed from amplification by maliciously oversized requests.
MAX_PROFILE_ENTRIES = 100
MAX_STATION_IDS = 200

# CORS headers attached to every Lambda response. The OPTIONS preflight is
# handled by API Gateway's mock integration (configured in template.yaml),
# but the actual POST response also needs Access-Control-Allow-Origin or
# the browser blocks it after the preflight succeeds.
CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
}


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
    stations: list[StationData]  # Single item for non-group, multiple for group

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
    """Parse JSON body from request. Handles string or dict body, returns {} on failure."""
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
    """Determine 'docks' or 'bikes' from body's type param (takes priority) or q param."""
    count_type = body.get("type")
    if count_type in ("docks", "bikes"):
        return count_type

    q = body.get("q", "")
    if q and "bike" in q.lower():
        return "bikes"

    return "docks"


def _get_all_station_ids(profile: list) -> list[str]:
    """Extract all station IDs from a profile configuration."""
    ids = []
    for entry in profile:
        if "id" in entry:
            # Single station
            ids.append(entry["id"])
        elif "stations" in entry:
            # Group of stations
            for station in entry["stations"]:
                ids.append(station["id"])
    return ids


def _validate_profile_size(profile: list) -> str | None:
    """Returns an error message if profile exceeds size limits, else None."""
    if len(profile) > MAX_PROFILE_ENTRIES:
        return f"profile too large (max {MAX_PROFILE_ENTRIES} entries)"
    total = 0
    for entry in profile:
        if "id" in entry:
            total += 1
        elif "stations" in entry:
            stations = entry.get("stations") or []
            if not isinstance(stations, list):
                return "stations must be an array"
            total += len(stations)
        if total > MAX_STATION_IDS:
            return f"too many station IDs (max {MAX_STATION_IDS} total)"
    return None


def _bad_request(message: str, content_type: str):
    """Return a 400 response."""
    if content_type == "text/plain":
        return {
            "statusCode": 400,
            "headers": {"content-type": "text/plain", **CORS_HEADERS},
            "body": f"Error: {message}",
        }
    return {
        "statusCode": 400,
        "headers": {"content-type": "application/json", **CORS_HEADERS},
        "body": json.dumps({"error": message}),
    }


def _fetch_station_data(profile: list) -> dict[str, StationData]:
    """
    Fetch real-time data for all stations in a profile.

    Returns dict of station_id -> StationData
    """
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
    """
    Process a profile configuration into EntryResults with real-time data.
    """
    results = []

    for entry in profile:
        is_primary = entry.get("primary", False)

        if "id" in entry:
            # Single station
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
            # Group of stations
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
    """
    Format dock availability as English sentence.

    Logic:
    - Always include primary entries
    - Include non-primary if total primary docks <= LOW_AVAILABILITY_THRESHOLD
    - For groups: collapse if first station has docks, expand if first is empty
    """
    primary_entries = [e for e in entries if e.is_primary]
    backup_entries = [e for e in entries if not e.is_primary]

    total_primary_docks = sum(e.total_docks for e in primary_entries)
    include_backups = total_primary_docks <= LOW_AVAILABILITY_THRESHOLD

    entries_to_report = primary_entries + (backup_entries if include_backups else [])

    parts = []
    for entry in entries_to_report:
        if not entry.is_group:
            # Single station
            parts.append(f"{entry.total_docks} docks at {entry.name}")
        else:
            # Group
            if entry.first_has_docks:
                # First station has docks - report group total
                parts.append(f"{entry.total_docks} docks at {entry.name}")
            else:
                # First station empty - report each individually
                for station in entry.stations:
                    parts.append(f"{station.docks} docks at {entry.name} {station.name}")

    if not parts:
        return "No stations configured"

    return ", ".join(parts)


def _format_bikes_english(entries: list[EntryResult]) -> str:
    """
    Format bike availability as English sentence.

    Logic:
    - Walk entries in order (primary first, then backup)
    - Skip stations with 0 ebikes
    - Early stop once accumulated ebikes >= LOW_AVAILABILITY_THRESHOLD
    - Fall back to classic bikes only if not enough ebikes found
    - For groups: collapse if first station has ebikes, expand if first is empty
      (skipping 0-ebike members in expanded view)
    """
    primary_entries = [e for e in entries if e.is_primary]
    backup_entries = [e for e in entries if not e.is_primary]
    all_entries = primary_entries + backup_entries

    parts = []
    accumulated_ebikes = 0

    for entry in all_entries:
        if accumulated_ebikes >= LOW_AVAILABILITY_THRESHOLD:
            break

        if not entry.is_group:
            if entry.total_ebikes > 0:
                parts.append(f"{entry.total_ebikes} ebikes at {entry.name}")
                accumulated_ebikes += entry.total_ebikes
        else:
            if entry.first_has_ebikes:
                parts.append(f"{entry.total_ebikes} ebikes at {entry.name}")
                accumulated_ebikes += entry.total_ebikes
            else:
                for station in entry.stations:
                    if accumulated_ebikes >= LOW_AVAILABILITY_THRESHOLD:
                        break
                    if station.ebikes > 0:
                        parts.append(
                            f"{station.ebikes} ebikes at {entry.name} {station.name}"
                        )
                        accumulated_ebikes += station.ebikes

    # Fall back to classic if not enough ebikes found anywhere
    if accumulated_ebikes < LOW_AVAILABILITY_THRESHOLD:
        classic_parts = []
        for entry in all_entries:
            if entry.total_classic > 0:
                classic_parts.append(f"{entry.total_classic} classic at {entry.name}")
        if classic_parts:
            if parts:
                parts.append("also " + ", ".join(classic_parts))
            else:
                parts.extend(classic_parts)

    if not parts:
        return "No bikes available"

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
    all_entries = primary_entries + backup_entries

    stations = []
    accumulated_ebikes = 0

    for entry in all_entries:
        if accumulated_ebikes >= LOW_AVAILABILITY_THRESHOLD:
            break

        if not entry.is_group:
            if entry.total_ebikes > 0:
                stations.append(
                    {
                        "name": entry.name,
                        "ebikes": entry.total_ebikes,
                        "classic": entry.total_classic,
                        "primary": entry.is_primary,
                    }
                )
                accumulated_ebikes += entry.total_ebikes
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
                accumulated_ebikes += entry.total_ebikes
            else:
                for station in entry.stations:
                    if accumulated_ebikes >= LOW_AVAILABILITY_THRESHOLD:
                        break
                    if station.ebikes > 0:
                        stations.append(
                            {
                                "name": f"{entry.name} {station.name}",
                                "ebikes": station.ebikes,
                                "classic": station.classic,
                                "primary": entry.is_primary,
                            }
                        )
                        accumulated_ebikes += station.ebikes

    showing_backups = any(not s.get("primary", True) for s in stations)
    showing_classic = accumulated_ebikes < LOW_AVAILABILITY_THRESHOLD

    return {
        "type": "bikes",
        "total_primary_ebikes": sum(e.total_ebikes for e in primary_entries),
        "showing_backups": showing_backups,
        "showing_classic": showing_classic,
        "stations": stations,
    }


def citibike_check(event, context):
    """Returns JSON with station counts."""
    logger.info("citibike_check called")

    body = _get_body(event)
    profile = body.get("profile")

    if not profile or not isinstance(profile, list):
        return _bad_request("profile is required and must be an array", "application/json")

    size_err = _validate_profile_size(profile)
    if size_err:
        return _bad_request(size_err, "application/json")

    count_type = _resolve_type(body)

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
            "headers": {"content-type": "application/json", **CORS_HEADERS},
            "body": json.dumps({"error": "internal error"}),
        }

    return {
        "statusCode": 200,
        "headers": {
            "content-type": "application/json; charset=utf-8",
            "cache-control": "no-store",
            **CORS_HEADERS,
        },
        "body": json.dumps(data),
    }


def citibike_check_english(event, context):
    """Returns English sentence describing station counts."""
    logger.info("citibike_check_english called")

    body = _get_body(event)
    profile = body.get("profile")

    if not profile or not isinstance(profile, list):
        return _bad_request("profile is required and must be an array", "text/plain")

    size_err = _validate_profile_size(profile)
    if size_err:
        return _bad_request(size_err, "text/plain")

    count_type = _resolve_type(body)

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
            "headers": {"content-type": "text/plain", **CORS_HEADERS},
            "body": "Error: internal error",
        }

    return {
        "statusCode": 200,
        "headers": {
            "content-type": "text/plain; charset=utf-8",
            "cache-control": "no-store",
            **CORS_HEADERS,
        },
        "body": message,
    }
