#!/usr/bin/env bash
set -euo pipefail

STACK_NAME="${STACK_NAME:-citibike-checker}"
REGION="${AWS_REGION:-us-east-1}"

# Copy config.json to src/ so it gets packaged with Lambda
if [ -f config.json ]; then
  cp config.json src/config.json
  echo "Copied config.json to src/"
else
  echo "ERROR: config.json not found. Copy config.example.json to config.json and configure it."
  exit 1
fi

sam build --use-container
sam deploy \
  --stack-name "$STACK_NAME" \
  --region "$REGION" \
  --capabilities CAPABILITY_IAM \
  --resolve-s3 \
  --no-confirm-changeset

API_URL="$(aws cloudformation describe-stacks --region "$REGION" --stack-name "$STACK_NAME" --query "Stacks[0].Outputs[?OutputKey=='ApiBaseUrl'].OutputValue" --output text)"
API_KEY="$(aws apigateway get-api-keys --region "$REGION" --name-query citibike-check-key --include-values --query "items[0].value" --output text)"

echo ""
echo "=========================================="
echo "Deployment complete!"
echo "=========================================="
echo "Endpoint: $API_URL"
echo "X-API-Key: $API_KEY"
echo ""
echo "Test with:"
echo "curl -sS \"$API_URL\" -H \"X-API-Key: $API_KEY\" | python3 -m json.tool"
