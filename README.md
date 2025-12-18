# citibike-checker

Check Citi Bike dock and bike availability at configured stations.

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
- **profiles**: Named location groups (e.g., "work", "home")

Example:
```json
{
  "users": {
    "josh": {
      "api_key": "sk_josh_abc123",
      "default_profile": "work",
      "profiles": {
        "work": [
          {"id": "station-uuid", "nickname": "43rd and Madison"},
          {"id": "station-uuid", "nickname": "grand central"}
        ],
        "home": [
          {"id": "station-uuid", "nickname": "my corner"}
        ]
      }
    }
  }
}
```

Generate API keys however you like (e.g., `openssl rand -hex 24`).

## Finding Station IDs

A local copy of all Citi Bike stations is in `data/stations.json` (2300+ stations, sorted by name).

To find a station ID:

```bash
# Search by street name
grep -i "42 st" data/stations.json

# Or use jq for prettier output
jq '.[] | select(.name | test("42 St"; "i")) | {name, station_id}' data/stations.json
```

Each station entry includes:
- `station_id` - UUID to use in config
- `name` - Human-readable location (e.g., "Park Ave & E 42 St")
- `capacity` - Total docks at station
- `lat`, `lon` - Coordinates

To refresh the station list (stations occasionally change):

```bash
./scripts/refresh_stations.sh
```

## API Endpoints

### `/citibike-check` (JSON)

Returns station counts as JSON.

Headers:
- `X-API-Key`: Your API key from config.json (required)

Query params:
- `q`: Natural language query (e.g., "how many docks at work") - parses profile and type
- `profile`: Profile name (default: user's default) - overrides q
- `type`: `docks` or `bikes` (default: `docks`) - overrides q

```bash
# Using explicit params
curl -sS "https://YOUR_API_URL/prod/citibike-check?type=bikes" \
  -H "X-API-Key: YOUR_API_KEY"

# Using natural language q param
curl -sS "https://YOUR_API_URL/prod/citibike-check?q=bikes%20at%20work" \
  -H "X-API-Key: YOUR_API_KEY"
```

### `/citibike-check-english` (Plain text)

Returns a human-readable sentence. Supports the same query params as above.

```bash
# Docks (default)
curl -sS "https://YOUR_API_URL/prod/citibike-check-english" \
  -H "X-API-Key: YOUR_API_KEY"
# Output: 53 docks at 43rd and Madison, 148 docks at grand central

# Bikes (with e-bike breakdown)
curl -sS "https://YOUR_API_URL/prod/citibike-check-english?type=bikes" \
  -H "X-API-Key: YOUR_API_KEY"
# Output: 0 ebikes and 0 classic at 43rd and Madison, 9 ebikes and 0 classic at grand central

# Natural language
curl -sS "https://YOUR_API_URL/prod/citibike-check-english?q=how%20many%20docks%20at%20work" \
  -H "X-API-Key: YOUR_API_KEY"
```

## Siri Shortcut Setup

Create one Shortcut named "Citi bike" with these actions:

1. **Dictate Text** - Prompt: "What do you want?"
2. **Get Contents of URL**:
   - URL: `https://YOUR_API_URL/prod/citibike-check-english`
   - Method: GET
   - Headers: `X-API-Key: YOUR_API_KEY`
   - Query: `q` = (Dictated Text)
3. **Speak Text** - Speak the response

Usage:
- "Hey Siri, Citi bike"
- Siri: "What do you want?"
- You: "How many docks at work?" or "Bikes at work?"

## Deploy to AWS Lambda

Prerequisites:
- AWS SAM CLI (`brew install aws-sam-cli`)
- Docker (for building)
- AWS credentials configured (`aws sso login --profile josh-personal`)
- `config.json` configured with users and API keys

Build and deploy:

```bash
sam build --use-container
AWS_PROFILE=josh-personal sam deploy \
  --stack-name citibike-checker \
  --region us-east-1 \
  --capabilities CAPABILITY_IAM \
  --resolve-s3 \
  --no-confirm-changeset
```

Or use the deploy script:

```bash
AWS_PROFILE=josh-personal ./deploy.sh
```

The API URL will be shown in the deployment output.

## Adding a New User

1. Generate an API key: `openssl rand -hex 24`
2. Add the user to `config.json` with their stations
3. Deploy: `AWS_PROFILE=josh-personal ./deploy.sh`
4. Share the API key and API URL with the user
