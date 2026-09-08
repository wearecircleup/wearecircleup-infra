#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SERVICE_DIR="${ROOT_DIR}/background_check_dispatcher"
ARTIFACT_DIR="${ROOT_DIR}/infra/artifacts/background-check-dispatcher"
BUILD_DIR="${ARTIFACT_DIR}/build"
ZIP_PATH="${ARTIFACT_DIR}/background_check_dispatcher_lambda.zip"

rm -rf "${BUILD_DIR}" "${ZIP_PATH}"
mkdir -p "${BUILD_DIR}"

cp "${SERVICE_DIR}/lambda_handler.py" "${BUILD_DIR}/lambda_handler.py"

(
  cd "${BUILD_DIR}"
  zip -rq "${ZIP_PATH}" .
)

echo "Built background check dispatcher Lambda package at ${ZIP_PATH}"
