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
