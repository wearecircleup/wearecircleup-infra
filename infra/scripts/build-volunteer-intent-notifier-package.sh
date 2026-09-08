#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SERVICE_DIR="${ROOT_DIR}/volunteer_intent_notifier"
ARTIFACT_DIR="${ROOT_DIR}/infra/artifacts/volunteer-intent-notifier"
BUILD_DIR="${ARTIFACT_DIR}/build"
ZIP_PATH="${ARTIFACT_DIR}/volunteer_intent_notifier_lambda.zip"

rm -rf "${BUILD_DIR}" "${ZIP_PATH}"
mkdir -p "${BUILD_DIR}"

cp "${SERVICE_DIR}/lambda_handler.py" "${BUILD_DIR}/lambda_handler.py"

(
  cd "${BUILD_DIR}"
  zip -rq "${ZIP_PATH}" .
)

echo "Built volunteer intent notifier Lambda package at ${ZIP_PATH}"
