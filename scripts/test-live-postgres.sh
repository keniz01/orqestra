#!/usr/bin/env bash
set -euo pipefail

compose=(docker compose -f docker-compose.test.yml)
cleanup() {
  "${compose[@]}" down --volumes --remove-orphans
}
trap cleanup EXIT

"${compose[@]}" up --detach --wait postgres
export ORQESTRA_TEST_POSTGRES_DSN="postgresql://orqestra_test:orqestra_test_password@127.0.0.1:55433/orqestra_test"
python3 -m pytest -q tests/integration/test_live_postgres.py
