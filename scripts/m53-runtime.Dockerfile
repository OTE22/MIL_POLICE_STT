# Cached deployment build; the normal backend Dockerfile also installs these
# dependencies through requirements.txt on a fresh build.
FROM military-stt/m53-tests:local AS dependencies
FROM military-stt/central-backend:before-m53-20261021
USER root
COPY --from=dependencies /usr/local/lib/python3.11/site-packages/reportlab /usr/local/lib/python3.11/site-packages/reportlab
COPY --from=dependencies /usr/local/lib/python3.11/site-packages/reportlab-4.4.3.dist-info /usr/local/lib/python3.11/site-packages/reportlab-4.4.3.dist-info
COPY --from=dependencies /usr/local/lib/python3.11/site-packages/bidi /usr/local/lib/python3.11/site-packages/bidi
COPY --from=dependencies /usr/local/lib/python3.11/site-packages/python_bidi-0.6.6.dist-info /usr/local/lib/python3.11/site-packages/python_bidi-0.6.6.dist-info
COPY --from=dependencies /usr/local/lib/python3.11/site-packages/arabic_reshaper /usr/local/lib/python3.11/site-packages/arabic_reshaper
COPY --from=dependencies /usr/local/lib/python3.11/site-packages/arabic_reshaper-3.0.0.dist-info /usr/local/lib/python3.11/site-packages/arabic_reshaper-3.0.0.dist-info
COPY --from=dependencies /usr/local/lib/python3.11/site-packages/charset_normalizer /usr/local/lib/python3.11/site-packages/charset_normalizer
COPY --from=dependencies /usr/local/lib/python3.11/site-packages/charset_normalizer-3.5.2.dist-info /usr/local/lib/python3.11/site-packages/charset_normalizer-3.5.2.dist-info
COPY --chown=app:app . /app
RUN chmod +x /app/docker-entrypoint.sh
USER app
