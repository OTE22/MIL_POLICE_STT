# Cached local runtime; no model downloads or dependency changes.
FROM military-stt/central-backend:before-html-statements-20261024
COPY --chown=app:app app /app/app
