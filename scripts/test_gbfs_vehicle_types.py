#!/usr/bin/env python3
"""
Test script to explore Citi Bike GBFS feeds for vehicle type information.
Checks if e-bike vs classic bike breakdowns are available.
"""

import json
import requests

# GBFS auto-discovery endpoint
GBFS_DISCOVERY_URL = "https://gbfs.citibikenyc.com/gbfs/gbfs.json"

# Our test stations
TEST_STATIONS = [
    "2af3ecc3-4f43-468a-a7cc-bb4804ee3e7a",  # E 43 St & Madison Ave
    "66dc8025-0aca-11e7-82f6-3863bb44ef7c",  # Park Ave & E 42 St
    "66dc7f02-0aca-11e7-82f6-3863bb44ef7c",  # Park Ave & E 41 St
]


def fetch_json(url: str) -> dict:
    """Fetch and parse JSON from URL."""
    print(f"Fetching: {url}")
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    return resp.json()


def main():
    print("=" * 60)
    print("GBFS Vehicle Type Discovery Test")
    print("=" * 60)

    # Step 1: Fetch auto-discovery
    print("\n1. Fetching GBFS auto-discovery...")
    discovery = fetch_json(GBFS_DISCOVERY_URL)

    print("\nAvailable feeds:")
    feeds = {}
    for feed in discovery.get("data", {}).get("en", {}).get("feeds", []):
        name = feed.get("name")
        url = feed.get("url")
        feeds[name] = url
        print(f"  - {name}: {url}")

    # Step 2: Check for vehicle_types feed
    print("\n2. Checking for vehicle_types feed...")
    if "vehicle_types" in feeds:
        print("   ✓ vehicle_types feed EXISTS!")
        vehicle_types = fetch_json(feeds["vehicle_types"])
        print("\n   Vehicle types defined:")
        types_by_id = {}
        for vt in vehicle_types.get("data", {}).get("vehicle_types", []):
            vt_id = vt.get("vehicle_type_id")
            name = vt.get("name")
            propulsion = vt.get("propulsion_type")
            form_factor = vt.get("form_factor")
            types_by_id[vt_id] = vt
            print(f"     - {vt_id}: {name} (propulsion: {propulsion}, form: {form_factor})")
    else:
        print("   ✗ vehicle_types feed NOT found")
        types_by_id = {}

    # Step 3: Fetch station_status and inspect our stations
    print("\n3. Checking station_status for vehicle type breakdowns...")
    status = fetch_json(feeds.get("station_status", "https://gbfs.citibikenyc.com/gbfs/en/station_status.json"))

    stations_by_id = {s["station_id"]: s for s in status.get("data", {}).get("stations", [])}

    for station_id in TEST_STATIONS:
        station = stations_by_id.get(station_id, {})
        print(f"\n   Station: {station_id}")
        print(f"   num_bikes_available: {station.get('num_bikes_available')}")
        print(f"   num_docks_available: {station.get('num_docks_available')}")
        print(f"   num_ebikes_available: {station.get('num_ebikes_available', 'NOT PRESENT')}")

        # Check for vehicle_types_available (GBFS 2.1+ standard)
        vta = station.get("vehicle_types_available")
        if vta:
            print(f"   vehicle_types_available: ✓ PRESENT!")
            for vt in vta:
                vt_id = vt.get("vehicle_type_id")
                count = vt.get("count")
                vt_info = types_by_id.get(vt_id, {})
                propulsion = vt_info.get("propulsion_type", "unknown")
                print(f"     - {vt_id}: {count} ({propulsion})")
        else:
            print(f"   vehicle_types_available: NOT PRESENT")

        # Check for vehicle_docks_available (GBFS 2.1+)
        vda = station.get("vehicle_docks_available")
        if vda:
            print(f"   vehicle_docks_available: ✓ PRESENT!")
            for vd in vda:
                print(f"     - {vd}")

        # Print raw station data for inspection
        print(f"\n   Raw station data keys: {list(station.keys())}")

    # Step 4: Check for free_bike_status (dockless/individual bikes)
    print("\n4. Checking for free_bike_status feed...")
    if "free_bike_status" in feeds:
        print("   ✓ free_bike_status feed EXISTS!")
        try:
            free_bikes = fetch_json(feeds["free_bike_status"])
            bikes = free_bikes.get("data", {}).get("bikes", [])
            print(f"   Total bikes in feed: {len(bikes)}")
            if bikes:
                print(f"   Sample bike keys: {list(bikes[0].keys())}")
                # Check first few for vehicle_type_id
                for bike in bikes[:3]:
                    print(f"     - bike_id: {bike.get('bike_id')}, vehicle_type_id: {bike.get('vehicle_type_id', 'NOT PRESENT')}")
        except Exception as e:
            print(f"   Error fetching free_bike_status: {e}")
    else:
        print("   ✗ free_bike_status feed NOT found")

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    sample_station = stations_by_id.get(TEST_STATIONS[0], {})
    has_ebikes_field = "num_ebikes_available" in sample_station
    has_vehicle_types = "vehicle_types_available" in sample_station
    has_vehicle_types_feed = "vehicle_types" in feeds

    print(f"\nCiti Bike GBFS provides:")
    print(f"  - num_ebikes_available field: {'YES' if has_ebikes_field else 'NO'}")
    print(f"  - vehicle_types_available breakdown: {'YES' if has_vehicle_types else 'NO'}")
    print(f"  - vehicle_types feed: {'YES' if has_vehicle_types_feed else 'NO'}")

    if has_ebikes_field:
        print("\n✓ You CAN distinguish e-bikes vs classic bikes using num_ebikes_available!")
        print("  Classic bikes = num_bikes_available - num_ebikes_available")
    elif has_vehicle_types:
        print("\n✓ You CAN distinguish e-bikes vs classic bikes using vehicle_types_available!")
    else:
        print("\n✗ Cannot distinguish e-bikes vs classic bikes from this GBFS feed.")


if __name__ == "__main__":
    main()
