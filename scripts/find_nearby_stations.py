#!/usr/bin/env python3
"""Find stations within 1 mile of a target station and plot them on a map."""

import json
import math
from pathlib import Path

import folium


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate the distance between two points on Earth in miles using Haversine formula."""
    R = 3959  # Earth's radius in miles

    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)

    a = math.sin(delta_lat / 2) ** 2 + \
        math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return R * c


def find_nearby_stations(target_id: str, max_distance_miles: float = 1.0) -> tuple[dict, list[dict]]:
    """Find all stations within max_distance_miles of the target station.

    Returns:
        Tuple of (target_station, list of nearby stations)
    """
    stations_path = Path(__file__).parent.parent / "data" / "stations.json"

    with open(stations_path) as f:
        stations = json.load(f)

    # Find the target station
    target_station = None
    for station in stations:
        if station.get("station_id") == target_id or station.get("external_id") == target_id:
            target_station = station
            break

    if not target_station:
        raise ValueError(f"Station {target_id} not found")

    target_lat = target_station["lat"]
    target_lon = target_station["lon"]

    print(f"Target station: {target_station['name']}")
    print(f"Location: ({target_lat}, {target_lon})")
    print(f"Finding stations within {max_distance_miles} mile(s)...\n")

    # Find nearby stations
    nearby = []
    for station in stations:
        if station.get("station_id") == target_id or station.get("external_id") == target_id:
            continue  # Skip the target station itself

        distance = haversine_distance(
            target_lat, target_lon,
            station["lat"], station["lon"]
        )

        if distance <= max_distance_miles:
            nearby.append({
                "station_id": station.get("station_id"),
                "name": station["name"],
                "lat": station["lat"],
                "lon": station["lon"],
                "distance_miles": round(distance, 3)
            })

    # Sort by distance
    nearby.sort(key=lambda x: x["distance_miles"])

    return target_station, nearby


def create_map(target_station: dict, nearby_stations: list[dict], output_path: Path) -> None:
    """Create an interactive map with the target and nearby stations."""
    # Center map on target station
    m = folium.Map(
        location=[target_station["lat"], target_station["lon"]],
        zoom_start=15,
        tiles="OpenStreetMap"
    )

    # Add target station marker (red)
    folium.Marker(
        location=[target_station["lat"], target_station["lon"]],
        popup=folium.Popup(
            f"<b>{target_station['name']}</b><br>Target Station",
            max_width=300
        ),
        icon=folium.Icon(color="red", icon="star"),
    ).add_to(m)

    # Add nearby station markers (blue)
    for station in nearby_stations:
        folium.Marker(
            location=[station["lat"], station["lon"]],
            popup=folium.Popup(
                f"<b>{station['name']}</b><br>Distance: {station['distance_miles']} miles",
                max_width=300
            ),
            icon=folium.Icon(color="blue", icon="info-sign"),
        ).add_to(m)

    # Save map
    m.save(output_path)
    print(f"Map saved to: {output_path}")


if __name__ == "__main__":
    target_station_id = "66dc7f02-0aca-11e7-82f6-3863bb44ef7c"
    max_distance = 0.2

    target_station, nearby_stations = find_nearby_stations(target_station_id, max_distance_miles=max_distance)

    print(f"Found {len(nearby_stations)} stations within {max_distance} mile(s):\n")
    print(f"{'Distance':<10} {'Name':<50} {'Station ID'}")
    print("-" * 100)

    for station in nearby_stations:
        print(f"{station['distance_miles']:<10} {station['name']:<50} {station['station_id']}")

    # Create and save map
    output_path = Path(__file__).parent.parent / "nearby_stations_map.html"
    create_map(target_station, nearby_stations, output_path)
