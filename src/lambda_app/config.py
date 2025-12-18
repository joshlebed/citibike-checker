"""
Configuration loader for citibike-checker.

Loads user configuration from config.json in the project root.
Each user has their own API key and set of location profiles.
"""

import json
import os
from pathlib import Path
from typing import Optional


def _find_config_file() -> Path:
    """Find config.json in the project root or Lambda environment."""
    # In Lambda, files are in /var/task
    lambda_path = Path("/var/task/config.json")
    if lambda_path.exists():
        return lambda_path

    # Local development: look relative to this file
    # src/lambda_app/config.py -> project root
    local_path = Path(__file__).parent.parent.parent / "config.json"
    if local_path.exists():
        return local_path

    raise FileNotFoundError(
        "config.json not found. Copy config.example.json to config.json and configure it."
    )


def _load_config() -> dict:
    """Load and parse config.json."""
    config_path = _find_config_file()
    with open(config_path) as f:
        return json.load(f)


# Load config at module import time
_CONFIG: Optional[dict] = None


def get_config() -> dict:
    """Get the loaded configuration (cached)."""
    global _CONFIG
    if _CONFIG is None:
        _CONFIG = _load_config()
    return _CONFIG


def get_user_by_api_key(api_key: str) -> Optional[dict]:
    """
    Look up a user by their API key.

    Returns dict with:
        - name: username
        - default_profile: their default profile name
        - profiles: dict of profile_name -> list of stations

    Returns None if API key not found.
    """
    config = get_config()
    for username, user_data in config.get("users", {}).items():
        if user_data.get("api_key") == api_key:
            return {
                "name": username,
                "default_profile": user_data.get("default_profile", "work"),
                "profiles": user_data.get("profiles", {}),
            }
    return None


def get_user_profiles(api_key: str) -> dict:
    """
    Get profiles for a user by API key.

    Returns dict of profile_name -> {"stations": [...]}
    Raises ValueError if API key not found.
    """
    user = get_user_by_api_key(api_key)
    if not user:
        raise ValueError("Invalid API key")

    # Convert to the format handler expects: {"profile_name": {"stations": [...]}}
    return {
        name: {"stations": stations}
        for name, stations in user["profiles"].items()
    }


def get_user_default_profile(api_key: str) -> str:
    """Get the default profile name for a user."""
    user = get_user_by_api_key(api_key)
    if not user:
        raise ValueError("Invalid API key")
    return user["default_profile"]
