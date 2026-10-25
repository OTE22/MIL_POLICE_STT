# Reuse installed dependencies; only report application code and migrations changed.
FROM military-stt/central-backend:report-runtime-base-20261025
COPY --chown=app:app app /app/app
COPY --chown=app:app alembic /app/alembic
