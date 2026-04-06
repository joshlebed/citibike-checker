#!/usr/bin/env python3
"""
Test the Lambda handlers locally against real Citibike data.

Usage:
    uv run scripts/test_local.py
    uv run scripts/test_local.py --type bikes
    uv run scripts/test_local.py --profile work --type docks
    uv run scripts/test_local.py --profile-file josh-profiles.json --profile work
"""

import argparse
import json
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from lambda_app.handler import citibike_check, citibike_check_english


def make_event(profile: list, q: str = None, count_type: str = None) -> dict:
    """Create a mock API Gateway event with profile in body."""
    body = {"profile": profile}
    if q:
        body["q"] = q
    if count_type:
        body["type"] = count_type
    return {"headers": {}, "body": json.dumps(body)}


def main():
    parser = argparse.ArgumentParser(description="Test Lambda handlers locally")
    parser.add_argument("--profile-file", default="josh-profiles.json", help="Path to profiles JSON file")
    parser.add_argument("--profile", default="work", help="Profile name")
    parser.add_argument("--type", default="docks", choices=["docks", "bikes"], help="Type")
    parser.add_argument("--q", default=None, help="Natural language query")
    parser.add_argument("--json", action="store_true", help="Use JSON endpoint")
    args = parser.parse_args()

    # Read profiles file
    profiles_path = Path(args.profile_file)
    if not profiles_path.exists():
        print(f"Error: {args.profile_file} not found")
        sys.exit(1)

    with open(profiles_path) as f:
        profiles = json.load(f)

    profile = profiles.get(args.profile)
    if not profile:
        print(f"Error: Profile '{args.profile}' not found")
        print(f"Available profiles: {list(profiles.keys())}")
        sys.exit(1)

    event = make_event(profile, q=args.q, count_type=args.type)

    print(f"Testing with profile: {args.profile}")
    print(f"Body params: type={args.type}, q={args.q}")
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
