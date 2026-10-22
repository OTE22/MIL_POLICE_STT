FROM military-stt/ldap-tests:local
USER root
RUN pip install --disable-pip-version-check --timeout 120 --retries 5 reportlab==4.4.3 python-bidi==0.6.6 arabic-reshaper==3.0.0 charset-normalizer==3.5.2
USER app
