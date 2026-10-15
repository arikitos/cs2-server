FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
COPY certificates/ /tmp/panel-certificates/
# Optional operator-supplied corporate CAs; HTTPS verification stays enabled.
RUN set -eu; \
    for certificate in /tmp/panel-certificates/*.crt; do \
        [ -f "$certificate" ] || continue; \
        openssl x509 -inform PEM -in "$certificate" \
            -out "/usr/local/share/ca-certificates/cs2-panel-$(basename "$certificate")"; \
    done; \
    update-ca-certificates; \
    PIP_CERT=/etc/ssl/certs/ca-certificates.crt pip install --no-cache-dir -r requirements.txt; \
    rm -rf /tmp/panel-certificates
COPY app.py .
COPY mode_defs.py .
COPY maintenance_guard.py .
COPY installation.py .
COPY config_guard.py .
COPY security.py .
COPY wsgi.py .
COPY templates templates
COPY static static
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=3)"
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "--threads", "4", "--timeout", "120", "wsgi:app"]
