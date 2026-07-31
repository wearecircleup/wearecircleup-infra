#!/usr/bin/env bash

set -euo pipefail

AWS_REGION="us-east-1"
STATE_BUCKET_NAME="wearecircleup-terraform-state-311923415472-us-east-1"

echo "Ensuring Terraform state bucket exists: ${STATE_BUCKET_NAME}"

if aws s3api head-bucket --bucket "${STATE_BUCKET_NAME}" 2>/dev/null; then
  echo "State bucket already exists."
else
  echo "Creating state bucket in ${AWS_REGION}."
  if [ "${AWS_REGION}" = "us-east-1" ]; then
    aws s3api create-bucket \
      --bucket "${STATE_BUCKET_NAME}" \
      --region "${AWS_REGION}"
  else
    aws s3api create-bucket \
      --bucket "${STATE_BUCKET_NAME}" \
      --region "${AWS_REGION}" \
      --create-bucket-configuration "LocationConstraint=${AWS_REGION}"
  fi
fi

aws s3api put-bucket-versioning \
  --bucket "${STATE_BUCKET_NAME}" \
  --versioning-configuration Status=Enabled

aws s3api put-bucket-encryption \
  --bucket "${STATE_BUCKET_NAME}" \
  --server-side-encryption-configuration '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'

aws s3api put-public-access-block \
  --bucket "${STATE_BUCKET_NAME}" \
  --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true

echo "Terraform state bucket is ready."
