#!/bin/bash
# Refresh the local station list from Citi Bike GBFS feed

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
OUTPUT_FILE="$PROJECT_DIR/data/stations.json"

echo "Fetching station list from Citi Bike GBFS..."

curl -sS "https://gbfs.citibikenyc.com/gbfs/en/station_information.json" | python3 -c "
import json
import sys

data = json.load(sys.stdin)
stations = data['data']['stations']

# Sort by name for easier browsing
stations.sort(key=lambda s: s.get('name', ''))

print(json.dumps(stations, indent=2))
" > "$OUTPUT_FILE"

COUNT=$(python3 -c "import json; print(len(json.load(open('$OUTPUT_FILE'))))")
echo "Saved $COUNT stations to data/stations.json"
