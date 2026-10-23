# Restore the pre-attribution application while retaining migration history.
FROM military-stt/central-backend:before-attribution-20261022
COPY --chown=app:app app /app/app
COPY --chown=app:app alembic /app/alembic
