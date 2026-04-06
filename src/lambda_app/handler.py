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


def _bad_request(message: str, content_type: str):
    """Return a 400 response."""
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
    - Prioritize e-bikes
    - Always report e-bikes for primary entries
    - If total primary e-bikes < LOW_AVAILABILITY_THRESHOLD:
      - Also report classic bikes
      - Also include non-primary entries
    - For groups: collapse if first station has e-bikes, expand if first is empty
    """
    primary_entries = [e for e in entries if e.is_primary]
    backup_entries = [e for e in entries if not e.is_primary]

    total_primary_ebikes = sum(e.total_ebikes for e in primary_entries)
    include_classic = total_primary_ebikes < LOW_AVAILABILITY_THRESHOLD
    include_backups = total_primary_ebikes < LOW_AVAILABILITY_THRESHOLD

    entries_to_report = primary_entries + (backup_entries if include_backups else [])

    parts = []

    # Report e-bikes
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

    # If low e-bikes, also report classic
    if include_classic:
        classic_parts = []
        for entry in entries_to_report:
            if not entry.is_group:
                classic_parts.append(f"{entry.total_classic} classic at {entry.name}")
            else:
                # For classic, just report total per group
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


def citibike_check(event, context):
    """Returns JSON with station counts."""
    logger.info("citibike_check called")

    body = _get_body(event)
    profile = body.get("profile")

    if not profile:
        return _bad_request("profile is required", "application/json")

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
    """Returns English sentence describing station counts."""
    logger.info("citibike_check_english called")

    body = _get_body(event)
    profile = body.get("profile")

    if not profile:
        return _bad_request("profile is required", "text/plain")

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
