#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SERVICE_DIR="${ROOT_DIR}/minor_authorization_validator"
ARTIFACT_DIR="${ROOT_DIR}/infra/artifacts/minor-authorization-validator"
BUILD_DIR="${ARTIFACT_DIR}/build"
ZIP_PATH="${ARTIFACT_DIR}/minor_authorization_validator_lambda.zip"

rm -rf "${BUILD_DIR}" "${ZIP_PATH}"
mkdir -p "${BUILD_DIR}"

cp "${SERVICE_DIR}/lambda_handler.py" "${BUILD_DIR}/lambda_handler.py"

(
  cd "${BUILD_DIR}"
  zip -rq "${ZIP_PATH}" .
)

echo "Built minor authorization validator Lambda package at ${ZIP_PATH}"
