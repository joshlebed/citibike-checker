#!/usr/bin/env bash
#
# Required env vars:
#   BUDGET_EMAIL  - email address for AWS Budget threshold notifications
#
# Optional env vars:
#   STACK_NAME              - CloudFormation stack name (default: citibike-checker)
#   AWS_REGION              - region to deploy into (default: us-east-1)
#   AWS_PROFILE             - AWS profile to use (default: josh-personal)
#   BUDGET_MONTHLY_LIMIT_USD - monthly budget cap in USD (default: 5)
#
set -euo pipefail

STACK_NAME="${STACK_NAME:-citibike-checker}"
REGION="${AWS_REGION:-us-east-1}"
export AWS_PROFILE="${AWS_PROFILE:-josh-personal}"
: "${BUDGET_EMAIL:?BUDGET_EMAIL must be set (email for AWS Budget alerts)}"
BUDGET_MONTHLY_LIMIT_USD="${BUDGET_MONTHLY_LIMIT_USD:-5}"

sam build --use-container
sam deploy \
  --stack-name "$STACK_NAME" \
  --region "$REGION" \
  --capabilities CAPABILITY_IAM \
  --resolve-s3 \
  --no-confirm-changeset \
  --parameter-overrides \
      "BudgetEmail=${BUDGET_EMAIL}" \
      "BudgetMonthlyLimitUsd=${BUDGET_MONTHLY_LIMIT_USD}"

API_URL="$(aws cloudformation describe-stacks --region "$REGION" --stack-name "$STACK_NAME" --query "Stacks[0].Outputs[?OutputKey=='ApiBaseUrl'].OutputValue" --output text)"
PRIMARY_KEY_ID="$(aws cloudformation describe-stacks --region "$REGION" --stack-name "$STACK_NAME" --query "Stacks[0].Outputs[?OutputKey=='PrimaryApiKeyId'].OutputValue" --output text)"
PRIMARY_KEY_VALUE="$(aws apigateway get-api-key --region "$REGION" --api-key "$PRIMARY_KEY_ID" --include-value --query value --output text)"

echo ""
echo "=========================================="
echo "Deployment complete!"
echo "=========================================="
echo "Endpoint:    $API_URL"
echo "API key ID:  $PRIMARY_KEY_ID"
echo "API key:     $PRIMARY_KEY_VALUE"
echo ""
echo "Add this header to your Siri Shortcut: x-api-key: $PRIMARY_KEY_VALUE"
echo ""
echo "Test with:"
echo "curl -sS \"$API_URL/citibike-check-english\" -X POST -H 'Content-Type: application/json' -H \"x-api-key: $PRIMARY_KEY_VALUE\" -d '{\"q\": \"docks\", \"profile\": [{\"name\": \"test\", \"id\": \"STATION_ID\", \"primary\": true}]}'"
