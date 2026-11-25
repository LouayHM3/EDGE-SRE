import argparse
import shutil
from pathlib import Path
from tempfile import NamedTemporaryFile
from zipfile import ZipFile

from src.lo2_source import RemoteMetrics

RAW = Path("data/raw/metrics")
SERVICES = ("client", "code", "key", "refresh-token", "service", "token", "user")


def download(count):
    with RemoteMetrics() as source, ZipFile(source) as archive:
        members = {Path(item.filename).name: item for item in archive.infolist()}
        runs = sorted({name.split("-")[0] for name in members if name.endswith("-node-metrics.csv")})
        if not 1 <= count <= len(runs):
            raise ValueError(f"Choose between 1 and {len(runs)} runs")
        selected = [runs[round(i * (len(runs) - 1) / max(1, count - 1))] for i in range(count)]
        RAW.mkdir(parents=True, exist_ok=True)
        for run in selected:
            for service in SERVICES:
                name = f"{run}-light-oauth2-oauth2-{service}-1-metrics.csv"
                item = members[name]
                path = RAW / name
                if path.exists() and path.stat().st_size == item.file_size:
                    continue
                source.seek(item.header_offset)
                source.read(item.compress_size + 4096)
                with NamedTemporaryFile(dir=RAW, suffix=".part", delete=False) as output:
                    temp = Path(output.name)
                    try:
                        with archive.open(item) as stream:
                            shutil.copyfileobj(stream, output)
                        output.close()
                        temp.replace(path)
                    finally:
                        output.close()
                        temp.unlink(missing_ok=True)
                print(name, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch selected LO2v2 metrics members")
    parser.add_argument("--runs", type=int, default=10)
    download(parser.parse_args().runs)
