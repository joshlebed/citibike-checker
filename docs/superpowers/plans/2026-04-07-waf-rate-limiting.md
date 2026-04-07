# AWS WAF Rate Limiting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an AWS WAFv2 WebACL with a rate-based rule in front of API Gateway so that billing-amplification attacks (where an attacker hammers the URL with bad keys) are blocked at the WAF layer instead of being rejected — and billed — by API Gateway.

**Architecture:** A regional WAFv2 WebACL with a single rate-based rule (100 requests / 5 minutes / source IP) is associated with the existing `CitibikeApi` prod stage. WAF inspects requests *before* they reach API Gateway; blocked requests return 403 from WAF and do not incur API Gateway request charges. WAF charges separately ($5/month per WebACL + $1/month per rule + $0.60 per million requests inspected) — at this scale, that's a fixed ~$6/month plus negligible variable cost.

**Tech Stack:** AWS SAM / CloudFormation, `AWS::WAFv2::WebACL`, `AWS::WAFv2::WebACLAssociation`, `aws cloudwatch get-metric-statistics` for verification.

**Key context for the engineer:**
- The codebase is at `/Users/joshlebed/code/citibike-checker`. Stack name is `citibike-checker`, region `us-east-1`, AWS profile `josh-personal`.
- The deploy script `./deploy.sh` requires `BUDGET_EMAIL` to be set as an env var.
- `template.yaml` already has API Gateway, two Lambdas, API key auth, a usage plan, a budget alarm, log groups, and CloudWatch alarms — your changes are *additive*, do not modify existing resources.
- The legitimate per-key throttle is 2 req/sec / burst 5 with a 200 req/day quota, so a real user will never come close to 100 req / 5 min from one IP. The threshold is comfortably above legit use.
- WAF "REGIONAL" scope is required for API Gateway REST APIs (CLOUDFRONT scope is for CloudFront distributions, not used here).
- Stage ARN format for the association is `arn:aws:apigateway:REGION::/restapis/REST-API-ID/stages/STAGE-NAME`.
- WAF rate-based rules count requests per source IP over a sliding window. The default `EvaluationWindowSec` is 300 (5 min). When the count exceeds `Limit`, all subsequent requests from that IP are blocked until the count drops back.
- WAF blocks return a 403 with body `Forbidden` (no JSON envelope). API Gateway 403s for missing API key return JSON `{"message":"Forbidden"}` — these are distinguishable in verification.

---

## File Structure

- **Modify:** `template.yaml` — add `CitibikeWebACL` resource, `CitibikeWebACLAssociation` resource, and a `WebAclArn` output. No existing resources change.
- **Modify:** `README.md` — add one line to the existing "Authentication" section noting the WAF rate cap.

No application code (Lambda handler, gbfs.py, deploy.sh) is touched. This is a pure infra change.

---

## Task 1: Add the WAFv2 WebACL resource

**Files:**
- Modify: `template.yaml` — append the new resource after the `MonthlyBudget` resource (currently around line 167–201) but before the `Outputs` section.

- [ ] **Step 1: Add the WebACL resource**

Open `template.yaml` and locate the `MonthlyBudget` resource (it ends with the third `Subscribers: - SubscriptionType: EMAIL` block). Immediately after the budget resource, before the `Outputs:` line, insert:

```yaml
  # WAFv2 Web ACL with a rate-based rule. WAF inspects requests before they
  # reach API Gateway and blocks IPs sending more than 100 requests in any
  # 5-minute window. Blocked requests do not incur API Gateway charges,
  # which protects against billing-amplification DDoS where an attacker
  # hammers the URL with invalid API keys.
  CitibikeWebACL:
    Type: AWS::WAFv2::WebACL
    Properties:
      Name: !Sub "${AWS::StackName}-webacl"
      Description: Rate-limiting WAF for citibike-checker API Gateway
      Scope: REGIONAL
      DefaultAction:
        Allow: {}
      VisibilityConfig:
        SampledRequestsEnabled: true
        CloudWatchMetricsEnabled: true
        MetricName: !Sub "${AWS::StackName}-webacl"
      Rules:
        - Name: RateLimitPerIP
          Priority: 1
          Action:
            Block: {}
          Statement:
            RateBasedStatement:
              Limit: 100
              AggregateKeyType: IP
          VisibilityConfig:
            SampledRequestsEnabled: true
            CloudWatchMetricsEnabled: true
            MetricName: !Sub "${AWS::StackName}-rate-limit"
```

- [ ] **Step 2: Validate the template**

Run: `sam validate --lint`
Expected: `/Users/joshlebed/code/citibike-checker/template.yaml is a valid SAM Template`

If lint complains, read the error carefully. Common issues:
- Indentation off by 2 spaces — YAML is whitespace-sensitive.
- Missing colon after a property name.
- `Scope` must be exactly `REGIONAL` (uppercase).
- `DefaultAction.Allow: {}` is intentional — `Allow` and `Block` are objects with no properties, the empty `{}` is required.

---

## Task 2: Associate the WebACL with the API Gateway stage

**Files:**
- Modify: `template.yaml` — append `CitibikeWebACLAssociation` immediately after the `CitibikeWebACL` resource you just added.

- [ ] **Step 1: Add the association resource**

Insert this directly after the `CitibikeWebACL` block:

```yaml
  CitibikeWebACLAssociation:
    Type: AWS::WAFv2::WebACLAssociation
    Properties:
      ResourceArn: !Sub "arn:aws:apigateway:${AWS::Region}::/restapis/${CitibikeApi}/stages/prod"
      WebACLArn: !GetAtt CitibikeWebACL.Arn
```

Note: `ResourceArn` uses the API Gateway stage ARN format which is *not* a normal CloudFormation `!Ref` — it must be constructed via `!Sub` from the API ID. The stage name (`prod`) is hardcoded because that's the `StageName` set on `CitibikeApi`.

- [ ] **Step 2: Validate the template again**

Run: `sam validate --lint`
Expected: `/Users/joshlebed/code/citibike-checker/template.yaml is a valid SAM Template`

---

## Task 3: Add the WebACL ARN to outputs

**Files:**
- Modify: `template.yaml` — add a new entry to the existing `Outputs:` block.

- [ ] **Step 1: Add the output**

Locate the `Outputs:` block at the bottom of `template.yaml`. After the `PrimaryApiKeyId` output, append:

```yaml
  WebAclArn:
    Description: ARN of the WAFv2 WebACL protecting the API
    Value: !GetAtt CitibikeWebACL.Arn
```

- [ ] **Step 2: Validate one more time**

Run: `sam validate --lint`
Expected: `/Users/joshlebed/code/citibike-checker/template.yaml is a valid SAM Template`

---

## Task 4: Deploy the changes

**Files:** none (deploy only)

- [ ] **Step 1: Run the deploy script**

Run: `BUDGET_EMAIL=joshlebed@gmail.com ./deploy.sh`
Expected: Build succeeds, then a CloudFormation changeset that includes:
- `+ Add CitibikeWebACL`
- `+ Add CitibikeWebACLAssociation`
- No `Modify` operations on existing resources (we did not change any of them)

Then `Successfully created/updated stack - citibike-checker in us-east-1` and the existing deployment summary banner with the API key.

If the deploy fails partway, read the CloudFormation error. The most likely failures:
- **WAF quota:** new AWS accounts have a default limit of 100 WebACLs per region — fine, but if that's exceeded the error is clear.
- **Permission denied:** the deploying IAM principal needs `wafv2:CreateWebACL`, `wafv2:AssociateWebACL`, `wafv2:GetWebACL`. Most admin profiles already have this; if `josh-personal` is restricted, the error names the missing action.
- **Association timing:** the WebACL must exist before association. CloudFormation handles this automatically because `CitibikeWebACLAssociation` references `CitibikeWebACL.Arn`.

- [ ] **Step 2: Confirm the WebACL exists in production**

Run: `aws wafv2 list-web-acls --scope REGIONAL --region us-east-1 --query "WebACLs[?Name=='citibike-checker-webacl']"`
Expected: a JSON array containing one entry with `Name`, `Id`, `ARN`, and `LockToken` fields.

- [ ] **Step 3: Confirm the association is in place**

Run:
```bash
WEB_ACL_ARN=$(aws wafv2 list-web-acls --scope REGIONAL --region us-east-1 --query "WebACLs[?Name=='citibike-checker-webacl'].ARN" --output text)
aws wafv2 list-resources-for-web-acl --web-acl-arn "$WEB_ACL_ARN" --resource-type API_GATEWAY --region us-east-1
```
Expected: A JSON object with `ResourceArns` containing one entry that matches `arn:aws:apigateway:us-east-1::/restapis/0j7cn0bse9/stages/prod`.

If `ResourceArns` is empty, the association was not created — check `aws cloudformation describe-stack-resource --stack-name citibike-checker --logical-resource-id CitibikeWebACLAssociation`.

---

## Task 5: Verify legitimate traffic still works

**Files:** none (verification)

- [ ] **Step 1: Single happy-path request with the real API key**

First fetch the key value:
```bash
KEY_VALUE=$(aws apigateway get-api-key --api-key 033y7kd0tf --include-value --query value --output text --region us-east-1)
```

Then:
```bash
curl -s -w "\nHTTP %{http_code}\n" -X POST "https://0j7cn0bse9.execute-api.us-east-1.amazonaws.com/prod/citibike-check-english" \
  -H "Content-Type: application/json" \
  -H "x-api-key: $KEY_VALUE" \
  -d '{"q":"docks","profile":[{"name":"43rd and Madison","id":"2af3ecc3-4f43-468a-a7cc-bb4804ee3e7a","primary":true}]}'
```
Expected: A line like `7 docks at 43rd and Madison` followed by `HTTP 200`. Exact dock count varies. WAF must not block this single request.

- [ ] **Step 2: Confirm an invalid-key request still gets 403 from API Gateway (not WAF)**

```bash
curl -s -i -X POST "https://0j7cn0bse9.execute-api.us-east-1.amazonaws.com/prod/citibike-check-english" \
  -H "Content-Type: application/json" \
  -H "x-api-key: bogus" \
  -d '{"q":"docks","profile":[]}' | head -15
```
Expected: `HTTP/2 403`, response body `{"message":"Forbidden"}`, and a header `x-amzn-errortype: ForbiddenException`. The `x-amzn-errortype` header confirms the rejection came from API Gateway (not WAF — WAF blocks do not include this header).

---

## Task 6: Verify WAF blocks rate violations

**Files:** none (verification)

- [ ] **Step 1: Fire 110 requests at the endpoint to exceed the 100/5min limit**

The WAF rate limit is per IP and counts ALL requests (allowed + blocked) regardless of whether they have a valid key. So we can use no key for this test — all requests will be 403'd anyway, but we just want to trip the rate limit.

```bash
for i in $(seq 1 110); do
  curl -s -o /dev/null -w "%{http_code}\n" -X POST \
    "https://0j7cn0bse9.execute-api.us-east-1.amazonaws.com/prod/citibike-check-english" \
    -H "Content-Type: application/json" \
    -d '{"q":"docks","profile":[]}'
done | sort | uniq -c
```
Expected: a count breakdown like `100 403` (but depends on timing). Initially you'll see all 403s (from API Gateway, missing key). Once the WAF threshold is hit, the source of the 403 changes to WAF. The status code is the same (403) but the body and headers differ.

This loop sends 110 requests as fast as bash + curl will go; WAF rate counting is sliding-window so the exact request number where blocking starts can vary by ±10. Don't sweat the precise count — what matters is that WAF *is* counting (verified in the next step).

- [ ] **Step 2: Inspect the response from a request you know was blocked by WAF**

After running the loop above (which leaves your IP in a "blocked" state for ~5 minutes), run a single request and inspect the headers:

```bash
curl -s -i -X POST "https://0j7cn0bse9.execute-api.us-east-1.amazonaws.com/prod/citibike-check-english" \
  -H "Content-Type: application/json" \
  -H "x-api-key: $KEY_VALUE" \
  -d '{"q":"docks","profile":[{"name":"43rd and Madison","id":"2af3ecc3-4f43-468a-a7cc-bb4804ee3e7a","primary":true}]}' | head -15
```

Expected: `HTTP/2 403`, response body literally `Forbidden` (no JSON braces, no `message` key), and the response should NOT contain `x-amzn-errortype: ForbiddenException`. This confirms the 403 came from the WAF layer, not API Gateway. The API key is valid here — the only reason for the block is the WAF rate rule.

If you instead get a 200 response, your IP was not yet blocked. Either you didn't send enough requests in step 1 or your IP changed between calls. Re-run step 1 with `seq 1 200`.

- [ ] **Step 3: Check the WAF CloudWatch metric for blocked requests**

```bash
aws cloudwatch get-metric-statistics \
  --region us-east-1 \
  --namespace AWS/WAFV2 \
  --metric-name BlockedRequests \
  --dimensions Name=WebACL,Value=citibike-checker-webacl Name=Region,Value=us-east-1 Name=Rule,Value=RateLimitPerIP \
  --start-time "$(date -u -v-15M +%Y-%m-%dT%H:%M:%SZ)" \
  --end-time "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --period 60 \
  --statistics Sum
```
Expected: A `Datapoints` array containing at least one entry with `Sum` > 0 within the last 15 minutes. If `Datapoints` is empty, WAF metrics may take 1-2 minutes to publish — wait and re-run. If after 5 minutes there's still nothing, the rule did not actually block anything (re-run task 6 step 1 with more requests).

- [ ] **Step 4: Wait out the rate-limit window so legit traffic recovers**

The block lasts up to ~5 minutes after you stop sending. Wait at least 5 minutes, then re-run task 5 step 1 (the happy-path curl). Expected: 200 OK with a normal dock count. This confirms WAF blocks expire correctly.

---

## Task 7: Document the change in README.md

**Files:**
- Modify: `README.md` — add one bullet under the "Authentication" section's existing controls list.

- [ ] **Step 1: Add the WAF bullet**

Open `README.md`, find the bullet list under "Authentication" that starts with `**Per-key quota:**` and ends with `**AWS Budget alarm:**`. Add a new bullet between the `Stage throttle` line and the `Account-wide Lambda cap` line:

```markdown
- **WAF rate cap:** AWS WAFv2 blocks any IP sending more than 100 requests in any 5-minute window, before the request reaches API Gateway billing
```

The full bullet list should now read:
```markdown
- **Per-key quota:** 200 requests/day per API key
- **Per-key throttle:** 2 req/sec, burst 5
- **Stage throttle:** 5 req/sec, burst 10 across all callers
- **WAF rate cap:** AWS WAFv2 blocks any IP sending more than 100 requests in any 5-minute window, before the request reaches API Gateway billing
- **Account-wide Lambda cap:** AWS default of 10 concurrent executions across the account (no per-function reservation needed at this scale; raise via Service Quotas if you ever need it)
- **AWS Budget alarm:** monthly cap (default $5) with email alerts
```

---

## Task 8: Commit and push

**Files:** none (git only)

- [ ] **Step 1: Stage and commit**

```bash
git add template.yaml README.md
git commit -m "$(cat <<'EOF'
feat: add AWS WAF rate-limiting in front of API Gateway

Adds an AWS WAFv2 regional WebACL with a single rate-based rule
(100 requests / 5 min / source IP) and associates it with the
prod API Gateway stage. Blocked requests are rejected at the WAF
layer and do not incur API Gateway request charges, closing the
billing-amplification gap left by stage throttling alone.

Cost impact: ~$6/month fixed (one WebACL + one rule) plus
$0.60/M requests inspected.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 2: Push to origin**

```bash
git push origin main
```
Expected: A new commit hash appears on `main` and the push succeeds without conflicts.

- [ ] **Step 3: Verify clean state**

```bash
git status
```
Expected: `Your branch is up to date with 'origin/main'.` and `nothing to commit, working tree clean` (modulo any untracked `.claude/` directory which is intentionally not committed).

---

## Rollback

If WAF causes problems for legitimate users (e.g. legit traffic gets caught by the rate limit during a sudden burst), there are two reversible options:

1. **Soft rollback (keep WAF, count only):** change the rule's `Action: Block: {}` to `Action: Count: {}` in `template.yaml` and redeploy. WAF will still count requests and emit metrics but will not block anything. Useful for tuning the limit before re-enabling blocks.

2. **Hard rollback (remove WAF entirely):** delete the `CitibikeWebACL`, `CitibikeWebACLAssociation`, and `WebAclArn` output from `template.yaml` and redeploy. CloudFormation deletes the association first, then the WebACL. Cost stops accruing immediately on deletion.

Both rollbacks are safe — neither affects the API key auth, throttling, or budget alarm.

---

## Self-Review

- **Spec coverage:** Item 5 from the audit was "Add AWS WAF with a rate-based rule (e.g. 100 req / 5min / IP) at ~$5/month with 30 min effort." ✅ Tasks 1-3 add the WAF resources with that exact threshold. Tasks 4-6 verify deployment and behavior. Task 7 documents it. Task 8 commits.
- **Placeholder scan:** No "TBD", "fill in", "appropriate error handling", or vague references. Every YAML block, curl command, and metric query is fully specified.
- **Type/name consistency:** `CitibikeWebACL` (resource name), `citibike-checker-webacl` (WAF Name property), `RateLimitPerIP` (rule name), `citibike-checker-rate-limit` (rule MetricName). Used consistently across tasks 1, 2, 3, 4, 5, 6, 7. The verification curls in task 6 reference the correct API ID `0j7cn0bse9` and stage `prod` as confirmed by the existing deploy.
- **Cost claim sanity:** $5 (WebACL) + $1 (rule) = $6 fixed. At 1000 requests/day inspection volume that's $0.60/M × 30000/M ≈ $0.018/month variable. Total ≈ $6.02/month, consistent with the audit's "~$5/month" rough estimate.
