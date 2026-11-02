from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .models import VerificationResult


class VerificationStore:
    def __init__(self, database_path: str | Path = "edge-sre.db") -> None:
        self.connection = sqlite3.connect(database_path)
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS verification_results (
                verification_id TEXT PRIMARY KEY,
                incident_id TEXT NOT NULL,
                action_id TEXT,
                status TEXT NOT NULL,
                checks TEXT NOT NULL,
                verified_at TEXT NOT NULL
            )
            """
        )
        self.connection.commit()

    def save(self, result: VerificationResult) -> None:
        self.connection.execute(
            """
            INSERT INTO verification_results
            (verification_id, incident_id, action_id, status, checks, verified_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                str(result.verification_id),
                str(result.incident_id),
                str(result.action_id) if result.action_id else None,
                result.status.value,
                json.dumps([check.model_dump() for check in result.checks]),
                result.verified_at.isoformat(),
            ),
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

