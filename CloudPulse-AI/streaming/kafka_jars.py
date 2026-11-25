"""Fetch the Spark 4.1.3 Kafka connector and its missing runtime dependencies."""

from concurrent.futures import ThreadPoolExecutor
from hashlib import sha1
from pathlib import Path
import sys
from urllib.request import urlopen

JARS = Path(sys.prefix) / "tools" / "spark-kafka-jars"
ARTIFACTS = [
    ("org.apache.spark", "spark-sql-kafka-0-10_2.13", "4.1.3"),
    ("org.apache.spark", "spark-token-provider-kafka-0-10_2.13", "4.1.3"),
    ("org.apache.kafka", "kafka-clients", "3.9.1"),
    ("org.apache.commons", "commons-pool2", "2.12.1"),
]


def fetch(artifact):
    group, name, version = artifact
    filename = f"{name}-{version}.jar"
    url = f"https://repo.maven.apache.org/maven2/{group.replace('.', '/')}/{name}/{version}/{filename}"
    with urlopen(url + ".sha1", timeout=30) as response:
        expected = response.read().decode().split()[0]
    with urlopen(url, timeout=45) as response:
        payload = response.read()
    if sha1(payload).hexdigest() != expected:
        raise ValueError(f"Checksum mismatch for {filename}")
    (JARS / filename).write_bytes(payload)


if __name__ == "__main__":
    JARS.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor() as workers:
        list(workers.map(fetch, ARTIFACTS))
