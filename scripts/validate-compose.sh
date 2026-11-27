#!/usr/bin/env bash
set -euo pipefail

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

printf 'ci-password\n' >"$tmp_dir/postgres-password"
printf 'tenant.example.auth0.com\n' >"$tmp_dir/auth0-domain"
printf 'https://api.example.com\n' >"$tmp_dir/auth0-audience"
printf '{"org-1":{"analytics":"postgresql://orqestra:ci-password@postgres:5432/orqestra"}}\n' \
  >"$tmp_dir/tenant-databases.json"

export POSTGRES_PASSWORD_FILE="$tmp_dir/postgres-password"
export AUTH0_DOMAIN_FILE="$tmp_dir/auth0-domain"
export AUTH0_AUDIENCE_FILE="$tmp_dir/auth0-audience"
export ORQESTRA_TENANT_DATABASES_FILE="$tmp_dir/tenant-databases.json"
export ORQESTRA_IMAGE_REGISTRY="ghcr.io/example/orqestra"
export ORQESTRA_IMAGE_TAG="ci"

docker compose config --quiet
docker compose -f docker-compose.yml -f docker-compose.prod.yml config --quiet
