FROM military-stt/desktop-agent:before-attribution-20261022
COPY --chown=agent:agent app /agent/app
COPY --chown=agent:agent scripts /agent/scripts
