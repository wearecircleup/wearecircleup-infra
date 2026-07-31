#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SERVICE_DIR="${ROOT_DIR}/eventbrite_api"
ARTIFACT_DIR="${ROOT_DIR}/infra/artifacts/eventbrite-api"
BUILD_DIR="${ARTIFACT_DIR}/build"
ZIP_PATH="${ARTIFACT_DIR}/eventbrite_api_lambda.zip"

rm -rf "${BUILD_DIR}" "${ZIP_PATH}"
mkdir -p "${BUILD_DIR}"

python -m pip install --upgrade pip
python -m pip install \
  --target "${BUILD_DIR}" \
  --requirement "${SERVICE_DIR}/requirements-lambda.txt"

cp -R "${SERVICE_DIR}/app" "${BUILD_DIR}/app"
cp "${SERVICE_DIR}/lambda_handler.py" "${BUILD_DIR}/lambda_handler.py"

(
  cd "${BUILD_DIR}"
  zip -rq "${ZIP_PATH}" .
)

echo "Built Lambda package at ${ZIP_PATH}"
