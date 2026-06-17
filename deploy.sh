#!/bin/bash
# ============================================================
# AWS CARE Operational Review Tool - Deployment Script
# ============================================================
# This script deploys the CARE Review Lambda function to your
# AWS account. It creates the necessary IAM role and Lambda
# function with a URL endpoint.
#
# Usage:
#   chmod +x deploy.sh
#   ./deploy.sh YOUR_AWS_ACCOUNT_ID
#
# Prerequisites:
#   - AWS CLI v2 installed and configured
#   - Authenticated to the target AWS account
#   - Region: us-east-1
# ============================================================

set -e

ACCOUNT_ID=${1:?"Usage: ./deploy.sh YOUR_AWS_ACCOUNT_ID"}
REGION="us-east-1"
FUNCTION_NAME="care-review-engine"
ROLE_NAME="care-review-engine-role"

echo ""
echo "============================================================"
echo "  Deploying AWS CARE Operational Review Tool"
echo "  Account: $ACCOUNT_ID"
echo "  Region:  $REGION"
echo "============================================================"
echo ""

echo "[1/5] Creating IAM Role..."
aws iam create-role \
  --role-name $ROLE_NAME \
  --assume-role-policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Principal": {"Service": "lambda.amazonaws.com"},
      "Action": "sts:AssumeRole"
    }]
  }' --no-cli-pager 2>/dev/null || echo "  Role already exists, continuing..."

echo "[2/5] Attaching permissions (read-only)..."
aws iam attach-role-policy --role-name $ROLE_NAME \
  --policy-arn arn:aws:iam::aws:policy/ReadOnlyAccess 2>/dev/null || true
aws iam attach-role-policy --role-name $ROLE_NAME \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole 2>/dev/null || true

echo "  Waiting 10 seconds for role to propagate..."
sleep 10

echo "[3/5] Packaging Lambda..."
cd "$(dirname "$0")"
zip -j function.zip lambda_function.py

echo "[4/5] Deploying Lambda function..."
aws lambda create-function \
  --function-name $FUNCTION_NAME \
  --runtime python3.12 \
  --handler lambda_function.lambda_handler \
  --role arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME} \
  --zip-file fileb://function.zip \
  --timeout 120 \
  --memory-size 256 \
  --region $REGION \
  --no-cli-pager 2>/dev/null || \
aws lambda update-function-code \
  --function-name $FUNCTION_NAME \
  --zip-file fileb://function.zip \
  --region $REGION \
  --no-cli-pager

echo "[5/5] Creating Function URL..."
URL=$(aws lambda create-function-url-config \
  --function-name $FUNCTION_NAME \
  --auth-type AWS_IAM \
  --region $REGION \
  --query 'FunctionUrl' --output text 2>/dev/null || \
aws lambda get-function-url-config \
  --function-name $FUNCTION_NAME \
  --region $REGION \
  --query 'FunctionUrl' --output text)

rm -f function.zip

echo ""
echo "============================================================"
echo "  DEPLOYMENT COMPLETE"
echo "============================================================"
echo ""
echo "  Function URL: $URL"
echo "  Function Name: $FUNCTION_NAME"
echo ""
echo "  Quick Test:"
echo "  aws lambda invoke --function-name $FUNCTION_NAME \\"
echo "    --payload '{\"tool\":\"generate_care_report\"}' \\"
echo "    --cli-binary-format raw-in-base64-out \\"
echo "    --region $REGION --no-cli-pager /tmp/care-report.json"
echo ""
echo "  Then view results:"
echo "  cat /tmp/care-report.json | python3 -m json.tool"
echo ""
echo "============================================================"
