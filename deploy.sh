#!/usr/bin/env bash
set -euo pipefail

STACK_NAME="${STACK_NAME:-citibike-checker}"
REGION="${AWS_REGION:-us-east-1}"
export AWS_PROFILE="${AWS_PROFILE:-josh-personal}"

sam build --use-container
sam deploy \
  --stack-name "$STACK_NAME" \
  --region "$REGION" \
  --capabilities CAPABILITY_IAM \
  --resolve-s3 \
  --no-confirm-changeset

API_URL="$(aws cloudformation describe-stacks --region "$REGION" --stack-name "$STACK_NAME" --query "Stacks[0].Outputs[?OutputKey=='ApiBaseUrl'].OutputValue" --output text)"

echo ""
echo "=========================================="
echo "Deployment complete!"
echo "=========================================="
echo "Endpoint: $API_URL"
echo ""
echo "Test with:"
echo "curl -sS \"$API_URL/citibike-check-english\" -X POST -H 'Content-Type: application/json' -d '{\"q\": \"docks\", \"profile\": [{\"name\": \"test\", \"id\": \"STATION_ID\", \"primary\": true}]}'"
