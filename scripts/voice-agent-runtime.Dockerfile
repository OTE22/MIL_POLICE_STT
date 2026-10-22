# Reuse the installed local inference dependencies and copy only the updated code.
# The regular desktop-agent/Dockerfile remains the fresh-install build.
FROM military-stt/desktop-agent:before-voice-overlap-20261022
COPY --chown=agent:agent app /agent/app
