# syntax=docker/dockerfile:1.7
# Optional pinned Nemotron runtime. Default agent model selection stays unchanged.
# Build through build-nemotron-agent.ps1, which verifies both named contexts.
ARG BASE_IMAGE=military-stt/desktop-agent:1.0.0-cpu
FROM ${BASE_IMAGE}
USER root
COPY --from=nemo_source /nemo /tmp/nemo-source/nemo
COPY --from=nemo_source /setup.py /pyproject.toml /README.md /LICENSE /MANIFEST.in /tmp/nemo-source/
COPY --from=nemo_wheels /lhotse-2.0.0a6-py3-none-any.whl /tmp/lhotse-2.0.0a6-py3-none-any.whl
RUN echo '15145bd072a3d6c5f6b52b07e40f0425f7189ec3a409fedd416c04331422cac3  /tmp/lhotse-2.0.0a6-py3-none-any.whl' | sha256sum -c - \
    && python -m pip install --no-deps --no-build-isolation --no-index --force-reinstall /tmp/nemo-source /tmp/lhotse-2.0.0a6-py3-none-any.whl \
    && rm -rf /tmp/nemo-source /tmp/lhotse-2.0.0a6-py3-none-any.whl /agent/tests /agent/.pytest_cache
COPY --chown=agent:agent app /agent/app
COPY --chown=agent:agent scripts /agent/scripts
ENV NEMO_SOURCE_REVISION=16b0ff2584c6355c53cbd6c28f0f431a76b24956
LABEL org.military-stt.nemo-source="https://github.com/NVIDIA-NeMo/Speech" \
      org.military-stt.nemo-revision="16b0ff2584c6355c53cbd6c28f0f431a76b24956" \
      org.military-stt.lhotse-version="2.0.0a6"
USER agent
