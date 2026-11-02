FROM python:3.11-slim

WORKDIR /workspace
COPY . /workspace
ENV EDGE_SRE_SIMULATION_ENV=container
CMD ["python", "-m", "pytest", "tests"]

