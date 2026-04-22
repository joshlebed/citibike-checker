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

## Architecture

```
┌────────────────────────┐     ┌────────────────────────┐
│  Station Picker        │     │  iOS Shortcut / Siri   │
│  (GitHub Pages)        │     │  (user's iPhone)       │
│  docs/index.html       │     │                        │
└───────────┬────────────┘     └───────────┬────────────┘
            │ test request                 │ voice query
            ▼                              ▼
     ┌───────────────────────────────────────────┐
     │   API Gateway REST (us-east-1)            │
     │   Throttle: 5 req/s, burst 10             │
     │   CORS: *  (public, no auth)              │
     └─────────────────┬─────────────────────────┘
                       │
          ┌────────────┴─────────────┐
          ▼                          ▼
    ┌──────────────┐          ┌───────────────────┐
    │ /check       │          │ /check-english    │
    │ returns JSON │          │ returns text      │
    └──────┬───────┘          └─────────┬─────────┘
           │                            │
           └────────────┬───────────────┘
                        ▼
            ┌──────────────────────────┐
            │  Lambda (Python 3.11)    │
            │  handler.py              │
            │  Account concurrency: 10 │
            └──────────────┬───────────┘
                           ▼
            ┌──────────────────────────┐
            │  Citi Bike GBFS feeds    │
            │  (public, unauthed)      │
            │  5s in-container cache   │
            └──────────────────────────┘
```

**Key properties:**

- **Stateless.** No database, no user accounts. Each request carries its own station profile. Multiple Shortcuts (work/home/etc.) just embed different profiles.
- **Two endpoints, one handler.** `/citibike-check` (JSON) and `/citibike-check-english` (text) are separate Lambdas but share `src/lambda_app/handler.py`. Siri Shortcuts prefer a fixed URL per output format over content-negotiation.
- **GBFS is the source of truth.** Live dock/bike counts come from Citi Bike's public GBFS feeds. A 5-second TTL cache lives inside the warm Lambda container to absorb bursts without hammering upstream.
- **Frontend is static.** `docs/` is served by GitHub Pages. It only calls the API at test time; the generated Shortcut config is what users actually ship to their phones.

**CloudFormation stacks:**

- `citibike-checker` — the main stack managed by `template.yaml` (Lambdas, API Gateway, log groups, alarms, budget). Deployed by SAM.
- `citibike-github-oidc` — bootstrap stack managed by `bootstrap/github-oidc.yaml` (GitHub Actions OIDC provider + deploy role). Deployed manually once.

## Deployment

### Ongoing deploys (CI/CD)

Every push to `main` triggers `.github/workflows/deploy.yml`. Two sequential jobs:

1. **test** — `pytest` via `uv`. Failures block the deploy.
2. **deploy** — `sam build && sam deploy`. Idempotent; a no-op push is a no-op deploy.

Typical run is ~45 seconds. View runs with `gh run list` or in the repo's Actions tab.

Manual re-run: `gh workflow run deploy.yml` or click *Run workflow* in the Actions tab.

### First-time setup

Two one-time steps before CI can deploy on your behalf:

```bash
# 1. Deploy the bootstrap stack (OIDC provider + IAM role).
#    Requires AWS credentials with admin-ish permissions in your account.
aws cloudformation deploy \
  --stack-name citibike-github-oidc \
  --template-file bootstrap/github-oidc.yaml \
  --capabilities CAPABILITY_NAMED_IAM \
  --region us-east-1

# 2. Store the budget-alert email as a GitHub Actions secret.
gh secret set BUDGET_EMAIL --body "you@example.com"
```

After those, the first push to `main` deploys the main stack. AWS Budgets will email you a confirmation link the first time — click it to start receiving alerts.

The role ARN in `.github/workflows/deploy.yml` (`arn:aws:iam::590184113718:role/...`) is hardcoded to this AWS account. If you fork, replace it with your own account ID, and update the defaults in `bootstrap/github-oidc.yaml` to your repo owner/name.

### Manual deploys

`bash deploy.sh` still works — use it when iterating on infra from a branch, or when the GitHub Actions path is broken. Requires local AWS credentials and Docker.

```bash
BUDGET_EMAIL=you@example.com ./deploy.sh
```

## CI/CD details

### OIDC auth (no long-lived AWS keys)

GitHub Actions authenticates to AWS using short-lived OIDC tokens instead of stored access keys. The flow:

1. The workflow requests an OIDC token from GitHub (`id-token: write` permission).
2. `aws-actions/configure-aws-credentials@v4` exchanges the token for temporary AWS credentials by calling `sts:AssumeRoleWithWebIdentity` against `github-actions-citibike-deploy`.
3. The role's trust policy (in `bootstrap/github-oidc.yaml`) requires the token's `sub` claim to match `repo:joshlebed/citibike-checker:ref:refs/heads/main`. Tokens from any other repo, branch, PR, or fork are rejected at the STS layer — no AWS policy needed.

This means there's nothing to rotate and nothing to leak. Compromising the GitHub repo would let an attacker deploy, but no attacker outside this specific repo+branch can assume the role at all.

### Bootstrap stack (why it's separate)

The GitHub Actions role can't create itself — that would be a chicken-and-egg problem. `bootstrap/github-oidc.yaml` lives in its own stack (`citibike-github-oidc`) deployed manually once. Changes to the role's permissions, trust policy, or the OIDC provider itself require a manual redeploy of the bootstrap stack; everything else (Lambda, API Gateway, alarms, budgets) flows through CI.

The role is granted `AdministratorAccess`. The trust condition is what actually limits blast radius, not the attached policy. Tightening the policy would mean enumerating every service SAM touches (Lambda, IAM roles for Lambda execution, API Gateway, CloudFormation, CloudWatch, S3 artifacts, Budgets) — deferred unless a real reason comes up.

### Secrets

- **`BUDGET_EMAIL`** (GitHub Actions secret) — passed to the `BudgetEmail` CloudFormation parameter. Update with `gh secret set BUDGET_EMAIL --body "new@example.com"`.

No AWS credentials are stored anywhere.

## Cost controls

The API is public — no auth required. Cost and abuse are bounded by layered defenses:

- **Stage throttle:** 5 requests/sec, burst 10 across all callers (API Gateway 429s excess at the edge). This is the primary ceiling on traffic reaching Lambda.
- **Account-wide Lambda cap:** AWS default of 10 concurrent executions across the account.
- **Request hardening:** profile entries capped at 100; total station IDs capped at 200; GBFS feeds cached 5 seconds per warm Lambda container; exception detail stripped from 500 responses.
- **Short log retention:** 1 day on both Lambda log groups.
- **AWS Budget alarm:** monthly cap (default $5) with email alerts at 50%, 80%, and forecasted 100%. **Notification-only** — does not stop spend.

### Decision log

**WAFv2 removed (April 2026).** Previously the stack included a WAFv2 WebACL with a rate-based rule. It was the dominant cost of the entire stack at roughly $6/month flat ($5 for the WebACL + $1 per rule), independent of traffic. Everything else combined (Lambda, API Gateway, S3, CloudWatch) came to fractions of a cent per month. For a personal-scale API whose actual traffic is a handful of Siri calls per day, the fixed fee wasn't justified.

The remaining tail risk is a sustained billing-amplification attack running up API Gateway per-request charges (at $3.50/million for REST). The 5 req/s stage throttle caps what passes through to Lambda but may or may not exempt 429'd requests from API Gateway billing (AWS docs are ambiguous). If a real attack ever materializes, either reattach the WAF or, cheaper, add Budget Actions that apply a deny-all IAM policy at a spend threshold.

**REST API Gateway, not HTTP API.** REST API Gateway supports per-stage throttling without usage plans/API keys, which matches the unauthenticated use case. HTTP API is ~3× cheaper per request but would need a different rate-limiting strategy. If request volume ever grows into a real line item, revisit.

**No reserved Lambda concurrency.** The AWS account has a total concurrency limit of 10 (low, due to account newness). Reserving concurrency on one Lambda would leave <10 unreserved, which AWS blocks. The account-wide cap of 10 serves as the de-facto ceiling for both functions combined.

**Stateless, profile-in-request.** No database, no user accounts, no auth. Each Siri Shortcut carries its own station config. Trades per-request payload size for zero backend state and simple ops.

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
