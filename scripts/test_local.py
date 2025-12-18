#!/usr/bin/env python3
"""
Test the Lambda handlers locally against real Citibike data.

Usage:
    uv run scripts/test_local.py
    uv run scripts/test_local.py --type bikes
    uv run scripts/test_local.py --profile work --type docks
"""

import argparse
import json
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from lambda_app.handler import citibike_check, citibike_check_english
from lambda_app.config import get_config


def make_event(api_key: str, query_params: dict = None) -> dict:
    """Create a mock API Gateway event."""
    return {
        "headers": {"X-API-Key": api_key},
        "queryStringParameters": query_params or {},
    }


def main():
    parser = argparse.ArgumentParser(description="Test Lambda handlers locally")
    parser.add_argument("--profile", default=None, help="Profile name")
    parser.add_argument("--type", default="docks", choices=["docks", "bikes"], help="Type")
    parser.add_argument("--q", default=None, help="Natural language query")
    parser.add_argument("--json", action="store_true", help="Use JSON endpoint")
    parser.add_argument("--user", default="josh", help="User from config")
    args = parser.parse_args()

    # Get API key for user
    config = get_config()
    user_config = config["users"].get(args.user)
    if not user_config:
        print(f"Error: User '{args.user}' not found in config.json")
        print(f"Available users: {list(config['users'].keys())}")
        sys.exit(1)

    api_key = user_config["api_key"]

    # Build query params
    params = {}
    if args.profile:
        params["profile"] = args.profile
    if args.type:
        params["type"] = args.type
    if args.q:
        params["q"] = args.q

    event = make_event(api_key, params)

    print(f"Testing with user: {args.user}")
    print(f"Query params: {params}")
    print("-" * 50)

    if args.json:
        response = citibike_check(event, None)
    else:
        response = citibike_check_english(event, None)

    print(f"Status: {response['statusCode']}")
    print(f"Content-Type: {response['headers'].get('content-type')}")
    print()

    if response["statusCode"] == 200:
        if args.json:
            data = json.loads(response["body"])
            print(json.dumps(data, indent=2))
        else:
            print("Response:")
            print(response["body"])
    else:
        print("Error:")
        print(response["body"])


if __name__ == "__main__":
    main()
