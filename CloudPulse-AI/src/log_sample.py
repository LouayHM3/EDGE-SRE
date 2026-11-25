"""Extract a bounded LO2v2 log sample using only selected ZIP members."""

import hashlib
import json
import re
from pathlib import Path
from zipfile import ZipFile

from src.lo2_source import RemoteMetrics
from src.preprocess import OUTPUT

URL = "https://zenodo.org/api/records/18937117/files/light-oauth2-logs.zip/content"
SIZE = 2_904_270_326
MAX_TRANSFER_BYTES = 16_000_000
MAX_LOG_BYTES = 12_000_000
SEQUENCE_LENGTH = 128
CACHE = Path("data/interim/log_templates.json")
SCENARIOS = (
    "correct", "access_token_form_urlencoded_400",
    "access_token_authorization_form_401", "get_token_404",
)
LOG = re.compile(r"\b(?:TRACE|DEBUG|INFO|WARN|ERROR|FATAL)\s+[\w.$]+\s+-?\s*(.*)")
TOKEN = re.compile(r"""\b\w+\b|[^\w\s]""")
FIELDS = re.compile(r"""https?://\S+|"[^"]*"|'[^']*'|\b\w{20,}\b|\b\w*\d\w*\b""")


def template_id(message):
    normalized = FIELDS.sub(" <value> ", message.lower())
    pattern = " ".join(TOKEN.findall(normalized)[:30])
    return hashlib.sha256(pattern.encode()).hexdigest()[:24]


def sample_logs():
    metadata = json.loads((OUTPUT / "preprocessing.json").read_text(encoding="utf-8"))
    runs = sorted(run for group in metadata["runs"].values() for run in group)
    documents = []
    with RemoteMetrics(URL, SIZE) as source, ZipFile(source) as archive:
        infos = [
            archive.getinfo(
                f"light-oauth2-logs/oauth2_logs_{run}/{scenario}/light-oauth2-oauth2-token-1.log"
            )
            for run in runs for scenario in SCENARIOS
        ]
        compressed = sum(info.compress_size for info in infos)
        if compressed > MAX_TRANSFER_BYTES or max(info.file_size for info in infos) > MAX_LOG_BYTES:
            raise ValueError("Selected ZIP members exceed the log sampling limits")
        for info in infos:
            _, folder, scenario, _ = info.filename.split("/")
            source.seek(info.header_offset)
            source.read(info.compress_size + 4096)
            templates = []
            line_count = 0
            with archive.open(info) as stream:
                for line in stream:
                    line_count += 1
                    if len(templates) < SEQUENCE_LENGTH:
                        match = LOG.search(line.decode("utf-8", errors="replace"))
                        if match:
                            templates.append(template_id(match[1]))
            if len(templates) != SEQUENCE_LENGTH:
                raise ValueError(f"Too few parseable events in {info.filename}")
            documents.append({
                "run": folder.removeprefix("oauth2_logs_"), "test": scenario,
                "lines": line_count, "templates": templates,
            })
            print(f"Sampled {folder}/{scenario}", flush=True)
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    temp = CACHE.with_suffix(".tmp")
    temp.write_text(json.dumps({"compressed_bytes": compressed, "documents": documents}), encoding="utf-8")
    temp.replace(CACHE)


if __name__ == "__main__":
    sample_logs()
