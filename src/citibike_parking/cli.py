from __future__ import annotations

import argparse
import json
import sys
from typing import List

from citibike_parking.gbfs import (
    DEFAULT_INFO_URL,
    DEFAULT_STATUS_URL,
    GbfsError,
    compute_parking_summary,
    summary_as_dict,
)


def _parse_station_ids(raw: str) -> List[str]:
    return [s.strip() for s in raw.split(",") if s.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="citibike-parking",
        description="Compute available Citi Bike docking spots across a set of station_ids.",
    )
    parser.add_argument(
        "--station-ids",
        required=True,
        help="Comma-separated station_ids",
    )
    parser.add_argument(
        "--status-url",
        default=DEFAULT_STATUS_URL,
        help="GBFS station_status.json URL",
    )
    parser.add_argument(
        "--info-url",
        default=DEFAULT_INFO_URL,
        help="GBFS station_information.json URL (set to empty to skip name lookups)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print JSON output (useful for testing Lambda response shape)",
    )

    args = parser.parse_args()

    station_ids = _parse_station_ids(args.station_ids)
    info_url = args.info_url.strip() or None

    try:
        summary = compute_parking_summary(
            station_ids,
            station_status_url=args.status_url,
            station_information_url=info_url,
        )
    except (GbfsError, ValueError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(2)

    if args.json:
        print(json.dumps(summary_as_dict(summary), indent=2, sort_keys=True))
        return

    # Human-friendly output
    print(f"Available work dock spots: {summary.available_spots}")
    for s in summary.stations:
        name = f" ({s.name})" if s.name else ""
        flags = []
        if s.is_renting is False:
            flags.append("not_renting")
        if s.is_returning is False:
            flags.append("not_returning")
        if s.is_installed is False:
            flags.append("not_installed")
        flag_str = f" [{' '.join(flags)}]" if flags else ""
        print(f"- {s.station_id}{name}: {s.docks_available} docks available, {s.bikes_available} bikes{flag_str}")
