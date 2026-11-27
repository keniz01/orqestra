# Deployment and rollback

The Compose stack requires provisioned secret files; no secret values belong in
the repository. Copy `.env.example` to an operator-managed environment file and
set the four `*_FILE` paths to files readable by the deployment user:

```bash
export ORQESTRA_IMAGE_REGISTRY=ghcr.io/keniz01/orqestra
export ORQESTRA_IMAGE_TAG=v0.1.0
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --wait
```

The deployment uses the control and web images tagged by the immutable release
tag. Validate the rendered configuration before starting services:

```bash
./scripts/validate-compose.sh
docker compose -f docker-compose.yml -f docker-compose.prod.yml config --quiet
```

To roll back, set `ORQESTRA_IMAGE_TAG` to a previously validated release tag
and recreate only the application services:

```bash
export ORQESTRA_IMAGE_TAG=v0.0.9
docker compose -f docker-compose.yml -f docker-compose.prod.yml pull control web
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --no-deps control web
```

PostgreSQL data is kept in the named volume and is not changed by an
application-image rollback. A release is not production-ready until the CI
workflow, Compose smoke test, live PostgreSQL test, health checks, and rollback
procedure have all been exercised in the target environment.
