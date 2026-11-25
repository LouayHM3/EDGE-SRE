# syntax=docker/dockerfile:1
FROM eclipse-temurin:17-jre AS java
FROM cloudpulse-ai-api:latest
COPY --from=java /opt/java/openjdk /opt/java/openjdk
COPY --from=spark_source . /opt/spark/source
ENV JAVA_HOME=/opt/java/openjdk SPARK_HOME=/opt/spark/source/deps \
    PYSPARK_PYTHON=/usr/local/bin/python \
    PYTHONPATH=/workspace:/opt/spark/source:/opt/spark/source/lib/py4j-0.10.9.9-src.zip
RUN --mount=type=secret,id=build_ca \
    set -eu; chmod +x "$SPARK_HOME"/bin/*; \
    if [ -f /run/secrets/build_ca ]; then \
      cat /etc/ssl/certs/ca-certificates.crt /run/secrets/build_ca > /tmp/lab-ca.pem; \
      export PIP_CERT=/tmp/lab-ca.pem; \
    fi; \
    python -m pip install --no-cache-dir 'pyarrow>=26,<27'; \
    rm -f /tmp/lab-ca.pem
WORKDIR /workspace
