import json
import os
from citibike_parking.gbfs import compute_parking_summary
from lambda_app.config import get_user_by_api_key, get_user_profiles, get_user_default_profile


def _get_api_key(event) -> str | None:
    """Extract API key from request headers."""
    headers = event.get("headers") or {}
    # Headers can be lowercase or mixed case depending on API Gateway config
    return headers.get("x-api-key") or headers.get("X-API-Key")


def _get_query_param(event, param, default=None):
    """Extract query parameter from API Gateway event."""
    params = event.get("queryStringParameters") or {}
    return params.get(param, default)


def _parse_natural_query(q: str, profile_names: list[str], default_profile: str) -> tuple[str, str]:
    """
    Parse natural language query to extract profile and type.

    Examples:
        "how many docks at work" -> ("work", "docks")
        "bikes at home" -> ("home", "bikes")
        "docks" -> (default_profile, "docks")

    Returns:
        (profile, count_type)
    """
    q_lower = q.lower()

    # Determine type
    if "bike" in q_lower:
        count_type = "bikes"
    elif "dock" in q_lower or "spot" in q_lower or "park" in q_lower:
        count_type = "docks"
    else:
        count_type = "docks"  # default

    # Determine profile by checking for profile names in the query
    profile = default_profile
    for profile_name in profile_names:
        if profile_name.lower() in q_lower:
            profile = profile_name
            break

    return profile, count_type


def _get_station_data(profiles: dict, profile_name: str, count_type: str = "docks"):
    """
    Fetch station data for a profile.

    Args:
        profiles: Dict of profile_name -> {"stations": [...]}
        profile_name: Name of the profile (e.g., "work", "home")
        count_type: "docks" or "bikes"

    Returns:
        Dict with station data grouped by nickname
    """
    profile = profiles.get(profile_name)
    if not profile:
        raise ValueError(f"Unknown profile: {profile_name}. Available: {list(profiles.keys())}")

    station_ids = [s["id"] for s in profile["stations"]]

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

    # Build lookup by station_id
    station_data = {s.station_id: s for s in summary.stations}

    # Group by nickname and sum counts
    result_by_nickname = {}
    for station_config in profile["stations"]:
        nickname = station_config["nickname"]
        station = station_data.get(station_config["id"])
        if station:
            if nickname not in result_by_nickname:
                result_by_nickname[nickname] = {
                    "docks": 0,
                    "bikes": 0,
                    "ebikes": 0,
                    "classic": 0,
                }
            result_by_nickname[nickname]["docks"] += station.docks_available
            result_by_nickname[nickname]["bikes"] += station.bikes_available
            result_by_nickname[nickname]["ebikes"] += station.ebikes_available
            result_by_nickname[nickname]["classic"] += station.classic_bikes_available

    # Build response based on count_type
    if count_type == "docks":
        stations = [
            {"nickname": nickname, "count": data["docks"]}
            for nickname, data in result_by_nickname.items()
        ]
    else:  # bikes
        stations = [
            {
                "nickname": nickname,
                "count": data["bikes"],
                "ebikes": data["ebikes"],
                "classic": data["classic"],
            }
            for nickname, data in result_by_nickname.items()
        ]

    return {
        "profile": profile_name,
        "type": count_type,
        "stations": stations,
    }


def _resolve_params(event, profiles: dict, default_profile: str):
    """
    Resolve profile and type from query params.
    If 'q' is provided, parse it for natural language.
    Explicit 'profile' and 'type' params override parsed values.
    """
    q = _get_query_param(event, "q")

    if q:
        parsed_profile, parsed_type = _parse_natural_query(
            q, list(profiles.keys()), default_profile
        )
    else:
        parsed_profile, parsed_type = default_profile, "docks"

    # Explicit params override
    profile = _get_query_param(event, "profile") or parsed_profile
    count_type = _get_query_param(event, "type") or parsed_type

    return profile, count_type


def _unauthorized_response(content_type: str = "application/json"):
    """Return a 401 Unauthorized response."""
    if content_type == "text/plain":
        return {
            "statusCode": 401,
            "headers": {"content-type": "text/plain"},
            "body": "Error: Invalid or missing API key",
        }
    return {
        "statusCode": 401,
        "headers": {"content-type": "application/json"},
        "body": json.dumps({"error": "Invalid or missing API key"}),
    }


def citibike_check(event, context):
    """
    Returns JSON with station counts.

    Headers:
        - X-API-Key: User's API key (required)

    Query params:
        - q: Natural language query (e.g., "how many docks at work")
        - profile: Profile name (default: user's default) - overrides q
        - type: "docks" or "bikes" (default: "docks") - overrides q
    """
    api_key = _get_api_key(event)
    if not api_key:
        return _unauthorized_response()

    user = get_user_by_api_key(api_key)
    if not user:
        return _unauthorized_response()

    profiles = {name: {"stations": stations} for name, stations in user["profiles"].items()}
    default_profile = user["default_profile"]

    profile, count_type = _resolve_params(event, profiles, default_profile)

    if count_type not in ("docks", "bikes"):
        return {
            "statusCode": 400,
            "headers": {"content-type": "application/json"},
            "body": json.dumps({"error": "type must be 'docks' or 'bikes'"}),
        }

    try:
        data = _get_station_data(profiles, profile, count_type)
    except ValueError as e:
        return {
            "statusCode": 400,
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
    """
    Returns English sentence describing station counts.

    Headers:
        - X-API-Key: User's API key (required)

    Query params:
        - q: Natural language query (e.g., "how many docks at work")
        - profile: Profile name (default: user's default) - overrides q
        - type: "docks" or "bikes" (default: "docks") - overrides q
    """
    api_key = _get_api_key(event)
    if not api_key:
        return _unauthorized_response("text/plain")

    user = get_user_by_api_key(api_key)
    if not user:
        return _unauthorized_response("text/plain")

    profiles = {name: {"stations": stations} for name, stations in user["profiles"].items()}
    default_profile = user["default_profile"]

    profile, count_type = _resolve_params(event, profiles, default_profile)

    if count_type not in ("docks", "bikes"):
        return {
            "statusCode": 400,
            "headers": {"content-type": "text/plain"},
            "body": "Error: type must be 'docks' or 'bikes'",
        }

    try:
        data = _get_station_data(profiles, profile, count_type)
    except ValueError as e:
        return {
            "statusCode": 400,
            "headers": {"content-type": "text/plain"},
            "body": f"Error: {e}",
        }

    # Build English sentence
    parts = []
    for s in data["stations"]:
        if count_type == "docks":
            parts.append(f"{s['count']} docks at {s['nickname']}")
        else:  # bikes - report ebikes first, then classic
            parts.append(f"{s['ebikes']} ebikes and {s['classic']} classic at {s['nickname']}")

    message = ", ".join(parts)

    return {
        "statusCode": 200,
        "headers": {
            "content-type": "text/plain; charset=utf-8",
            "cache-control": "no-store",
        },
        "body": message,
    }
