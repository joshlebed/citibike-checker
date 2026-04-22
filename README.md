# citibike-checker

Check Citi Bike dock and bike availability with smart priority-based reporting. Designed for Siri Shortcuts — ask "Hey Siri, Citi bike work docks" and hear availability at your configured stations.

## How It Works

1. **Pick your stations** using the [Station Picker](https://joshlebed.github.io/citibike-checker/) web app
2. **Generate a config** — the picker builds a JSON payload with your selected stations
3. **Create a Siri Shortcut** that POSTs your config to the API and speaks the result

The server is stateless — your station config lives in each Shortcut, not on the server. Create multiple Shortcuts for different locations (work, home, etc.).

## Quick Start (For Users)

1. Visit the [Station Picker](https://joshlebed.github.io/citibike-checker/)
2. Find your stations on the map (search by address or use your location)
3. Click stations to select them, mark your closest as "primary"
4. Click "Generate Config" and follow the Siri Shortcut instructions

## API Endpoints

### `POST /citibike-check-english` (Plain text for Siri)

Returns a human-readable sentence.

```bash
curl -sS "https://YOUR_API_URL/prod/citibike-check-english" \
  -X POST \
  -H "Content-Type: application/json" \
  -d '{
    "q": "docks",
    "profile": [
      {"name": "43rd and Madison", "id": "2af3ecc3-4f43-468a-a7cc-bb4804ee3e7a", "primary": true},
      {"name": "grand central", "primary": true, "stations": [
        {"id": "66dc8025-0aca-11e7-82f6-3863bb44ef7c", "name": "north"},
        {"id": "66dc7f02-0aca-11e7-82f6-3863bb44ef7c", "name": "south"}
      ]}
    ]
  }'
# Output: 10 docks at 43rd and Madison, 27 docks at grand central
```

### `POST /citibike-check` (JSON)

Returns structured JSON with station data. Same request format.

### Request Format

```json
{
  "q": "docks",
  "profile": [
    {
      "name": "station display name",
      "id": "station-uuid",
      "primary": true
    },
    {
      "name": "group name",
      "primary": true,
      "stations": [
        { "id": "station-uuid-1", "name": "sub-name" },
        { "id": "station-uuid-2", "name": "sub-name" }
      ]
    }
  ]
}
```

- `q`: `"docks"` or `"bikes"` (defaults to `"docks"`)
- `type`: explicit override for `q`
- `profile`: array of station entries (single stations or groups)
- `primary: true`: always reported. Non-primary entries only shown when primary availability is low.

### Smart Reporting Logic

**Docks:**
- Primary entries always shown
- If primary total <=3 docks, backup entries also shown
- Groups collapse to total if first station has availability; expand if first is empty

**Bikes:**
- E-bikes prioritized over classic bikes
- If primary e-bikes <3, also report classic bikes and backup stations

## Deploy Your Own

Prerequisites: AWS SAM CLI, Docker, AWS credentials.

```bash
# Build and deploy the Lambda. BUDGET_EMAIL is required and is used
# for AWS Budget threshold notifications (50%, 80%, forecasted 100%).
BUDGET_EMAIL=you@example.com ./deploy.sh
```

The script prints the API Gateway URL after deployment. AWS Budgets will email you a confirmation link the first time the budget is created; click it to start receiving alerts.

The station picker web app is in `docs/` and can be hosted on GitHub Pages or any static hosting.

## Cost controls

The API is public — no auth required. Cost and abuse are bounded by layered defenses:

- **Stage throttle:** 5 requests/sec, burst 10 across all callers (API Gateway 429s excess at the edge). This is the primary ceiling on traffic reaching Lambda.
- **Account-wide Lambda cap:** AWS default of 10 concurrent executions across the account
- **Request hardening:** profile entries capped at 100; total station IDs capped at 200; GBFS feeds cached 5 seconds per warm Lambda container; exception detail stripped from 500 responses
- **Short log retention:** 1 day on both Lambda log groups
- **AWS Budget alarm:** monthly cap (default $5) with email alerts at 50%, 80%, and forecasted 100%

WAF was previously attached ($5/mo WebACL + $1/mo per rule) but was removed: it was the dominant cost of the whole stack (~$6/mo flat) for a personal-scale API, and the remaining layers above bound the realistic attack surface. A sustained billing-amplification DDoS could still incur per-request API Gateway charges beyond the budget — if that becomes a concern, reattach a WAFv2 rate-based rule.

## Development

```bash
uv sync

# Run tests
uv run pytest tests/ -v
uv run scripts/test_mock.py -v

# Test locally against real data (requires josh-profiles.json or similar)
uv run scripts/test_local.py --profile work --type docks

# Refresh station data
./scripts/refresh_stations.sh
```

## Finding Station IDs

Use the [Station Picker](https://joshlebed.github.io/citibike-checker/) web app, or search locally:

```bash
grep -i "42 st" data/stations.json
jq '.[] | select(.name | test("42 St"; "i")) | {name, station_id}' data/stations.json
```
