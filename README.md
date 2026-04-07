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

All endpoints require an API key passed in the `x-api-key` header. See [Authentication](#authentication) below.

### `POST /citibike-check-english` (Plain text for Siri)

Returns a human-readable sentence.

```bash
curl -sS "https://YOUR_API_URL/prod/citibike-check-english" \
  -X POST \
  -H "Content-Type: application/json" \
  -H "x-api-key: YOUR_API_KEY" \
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

The script prints the API Gateway URL and the primary API key after deployment. Save the key — you'll add it to each Siri Shortcut as an `x-api-key` header. AWS Budgets will email you a confirmation link the first time the budget is created; click it to start receiving alerts.

The station picker web app is in `docs/` and can be hosted on GitHub Pages or any static hosting.

## Authentication

The API rejects all requests without a valid `x-api-key` header. Cost controls layered in:

- **Per-key quota:** 200 requests/day per API key
- **Per-key throttle:** 2 req/sec, burst 5
- **Stage throttle:** 5 req/sec, burst 10 across all callers
- **Account-wide Lambda cap:** AWS default of 10 concurrent executions across the account (no per-function reservation needed at this scale; raise via Service Quotas if you ever need it)
- **AWS Budget alarm:** monthly cap (default $5) with email alerts

### Retrieve your API key

The deploy script prints it for you. To re-fetch it later:

```bash
KEY_ID=$(aws cloudformation describe-stacks --stack-name citibike-checker \
  --query "Stacks[0].Outputs[?OutputKey=='PrimaryApiKeyId'].OutputValue" --output text)
aws apigateway get-api-key --api-key "$KEY_ID" --include-value --query value --output text
```

### Add the key to your Siri Shortcut

In the **Get Contents of URL** action, add a second header alongside `Content-Type`:

- **Key:** `x-api-key`
- **Value:** *your API key*

### Adding more keys (e.g. for friends/family)

Edit `template.yaml` and duplicate `PrimaryApiKey` + `PrimaryApiKeyAssociation` with new logical names (e.g. `AliceApiKey`, `AliceApiKeyAssociation`). Add a matching `Outputs` entry, redeploy, then fetch the new key value with the same command above. To revoke a key, delete the resources or set `Enabled: false`.

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
