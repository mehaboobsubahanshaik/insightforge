# InsightForge API container (insightforge-api)
FROM python:3.12-slim

WORKDIR /srv

# ml package first (backend imports insightforge_ml)
COPY ml /srv/ml
RUN pip install --no-cache-dir /srv/ml

# backend package
COPY backend/pyproject.toml /srv/backend/pyproject.toml
COPY backend/src /srv/backend/src
COPY backend/tests /srv/backend/tests
RUN pip install --no-cache-dir "/srv/backend[dev]"

# migrations live in the database/ folder; alembic.ini points at them
COPY backend/alembic.ini /srv/backend/alembic.ini
COPY database/migrations /srv/database/migrations

WORKDIR /srv/backend
EXPOSE 8000
# Migrations run on every boot (idempotent), then the API starts.
CMD ["sh", "-c", "python -m alembic upgrade head && python -m uvicorn insightforge_api.main:app --host 0.0.0.0 --port 8000"]
