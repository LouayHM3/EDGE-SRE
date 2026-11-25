# syntax=docker/dockerfile:1
FROM python:3.11-slim
WORKDIR /app
COPY monitoring/requirements-api.txt /tmp/requirements-api.txt
RUN --mount=type=secret,id=build_ca \
    set -eu; \
    if [ -f /run/secrets/build_ca ]; then \
      cat /etc/ssl/certs/ca-certificates.crt /run/secrets/build_ca > /tmp/cloudpulse-ca.pem; \
      export PIP_CERT=/tmp/cloudpulse-ca.pem; \
    fi; \
    python -m pip install --no-cache-dir torch==2.15.0+cpu --index-url https://download.pytorch.org/whl/cpu; \
    python -m pip install --no-cache-dir -r /tmp/requirements-api.txt; \
    rm -f /tmp/cloudpulse-ca.pem
COPY api api
COPY src src
CMD ["python", "-m", "uvicorn", "api.app:app", "--host", "0.0.0.0", "--port", "8000"]
