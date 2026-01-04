# citibike-checker

Check Citi Bike dock and bike availability at configured stations with smart priority-based reporting.

## Setup

```bash
cp config.example.json config.json
# Edit config.json with your stations and API keys
uv sync
```

## Configuration

All user configuration lives in `config.json` (not in version control). See `config.example.json` for the format.

Each user has:

- **api_key**: Unique key for API authentication (you create these)
- **default_profile**: Which profile to use when none specified
- **profiles**: Named location profiles (e.g., "work", "home")

### Profile Structure

Profiles are arrays of station entries, ordered by preference. Each entry can be:

**Single station:**

```json
{ "name": "43rd and Madison", "id": "station-uuid", "primary": true }
```

**Group of stations** (e.g., two stations right next to each other):

```json
{
  "name": "grand central",
  "primary": true,
  "stations": [
    { "id": "station-uuid-1", "name": "north" },
    { "id": "station-uuid-2", "name": "south" }
  ]
}
```

### Primary vs Backup

- `"primary": true` - Always reported
- No `primary` flag - Only reported if total primary availability ≤3

### Smart Reporting Logic

**Docks:**

- Primary entries always shown
- If primary total ≤3 docks, backup entries also shown
- Groups collapse to total if first station has availability; expand if first is empty

**Bikes:**

- E-bikes prioritized over classic bikes
- If primary e-bikes <3, also report classic bikes and backup stations
- Same group collapsing logic as docks

### Example Config

```json
{
  "users": {
    "josh": {
      "api_key": "sk_josh_abc123",
      "default_profile": "work",
      "profiles": {
        "work": [
          {
            "name": "43rd and Madison",
            "id": "2af3ecc3-4f43-468a-a7cc-bb4804ee3e7a",
            "primary": true
          },
          {
            "name": "grand central",
            "primary": true,
            "stations": [
              { "id": "66dc8025-0aca-11e7-82f6-3863bb44ef7c", "name": "north" },
              { "id": "66dc7f02-0aca-11e7-82f6-3863bb44ef7c", "name": "south" }
            ]
          },
          {
            "name": "40th",
            "stations": [
              { "id": "c638ec67-9ac0-416f-944f-619926144931", "name": "east" },
              { "id": "2098359443836787630", "name": "west" }
            ]
          }
        ]
      }
    }
  }
}
```

Generate API keys: `openssl rand -hex 24`

## Finding Station IDs

A local copy of all Citi Bike stations is in `data/stations.json` (2300+ stations, sorted by name).

```bash
# Search by street name
grep -i "42 st" data/stations.json

# Or use jq for prettier output
jq '.[] | select(.name | test("42 St"; "i")) | {name, station_id}' data/stations.json
```

To refresh the station list:

```bash
./scripts/refresh_stations.sh
```

## API Endpoints

### `/citibike-check-english` (Plain text for Siri) - POST

Returns a human-readable sentence. Uses POST with JSON body to avoid URL encoding issues with Siri Shortcuts.

```bash
curl -sS "https://YOUR_API_URL/prod/citibike-check-english" \
  -X POST \
  -H "X-API-Key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{}'
# Output: 10 at 43rd and Madison, 27 at grand central docks

curl -sS "https://YOUR_API_URL/prod/citibike-check-english" \
  -X POST \
  -H "X-API-Key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"q": "bikes at work"}'
# Output: 5 ebikes at 43rd and Madison, 8 ebikes at grand central
```

### `/citibike-check` (JSON) - GET

Returns structured JSON with station data.

Query params:

- `q`: Natural language query (e.g., "docks at work", "bikes at home")
- `profile`: Profile name (overrides q)
- `type`: `docks` or `bikes` (overrides q)

## Siri Shortcut Setup

Create one Shortcut named "Citi bike" with these actions:

1. **Dictate Text** - Stop listening: After Short Pause
2. **Get Contents of URL**:
   - URL: `https://YOUR_API_URL/prod/citibike-check-english`
   - Method: **POST**
   - Headers: `X-API-Key: YOUR_API_KEY`
   - Request Body: **JSON**
   - Add key: `q` = (Dictated Text)
3. **Speak Text** - Speak the response

Usage:

- "Hey Siri, Citi bike"
- Siri: (listens)
- You: "docks at work" or "bikes at work"

Note: POST with JSON body avoids URL encoding issues that can truncate dictated text.

## Deploy to AWS Lambda

Prerequisites:

- AWS SAM CLI (`brew install aws-sam-cli`)
- Docker (for building)
- AWS credentials configured
- `config.json` configured

```bash
./deploy.sh
```

The API URL will be shown in the deployment output.

## Adding a New User

1. Generate an API key: `openssl rand -hex 24`
2. Add the user to `config.json` with their stations
3. Deploy: `./deploy.sh`
4. Share the API key and API URL with the user

## AWS Operations

All AWS commands require the profile prefix: `AWS_PROFILE=josh-personal`

### Authentication

```bash
# Login via SSO (required when token expires)
aws sso login

# Verify authentication
aws sts get-caller-identity
```

### Viewing CloudWatch Logs

Lambda functions log to CloudWatch. Log groups:

- `/aws/lambda/citibike-checker-CitibikeCheckFunction-*` (JSON endpoint)
- `/aws/lambda/citibike-checker-CitibikeCheckEnglishFunction-*` (English endpoint)

```bash
# List log groups
aws logs describe-log-groups \
  --log-group-name-prefix "/aws/lambda/citibike" \
  --query 'logGroups[*].logGroupName' --output text

# View recent logs (last hour) for the English endpoint
aws logs tail \
  "/aws/lambda/citibike-checker-CitibikeCheckEnglishFunction-1IF6TcSAgNb1" \
  --since 1h

# View logs from a specific date (use epoch milliseconds)
# Get epoch: python3 -c "import datetime; print(int(datetime.datetime(2025, 12, 25).timestamp() * 1000))"
aws logs filter-log-events \
  --log-group-name "/aws/lambda/citibike-checker-CitibikeCheckEnglishFunction-1IF6TcSAgNb1" \
  --start-time 1735102800000 \
  --query 'events[*].[timestamp,message]' --output text

# Follow logs in real-time
aws logs tail \
  "/aws/lambda/citibike-checker-CitibikeCheckEnglishFunction-1IF6TcSAgNb1" \
  --follow
```

### Deploying

```bash
# Build and deploy
./deploy.sh

# Or manually with SAM
sam build
sam deploy
```

The deploy script handles building and deploying. The API URL is shown in the output.
