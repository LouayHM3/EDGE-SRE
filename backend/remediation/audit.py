from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import UUID

from .models import ActionStatus, RemediationRequest, RemediationResult


class AuditLog:
    def __init__(self, database_path: str | Path = "edge-sre.db") -> None:
        self.connection = sqlite3.connect(database_path)
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS remediation_audit (
                action_id TEXT PRIMARY KEY,
                incident_id TEXT NOT NULL,
                action TEXT NOT NULL,
                requested_by TEXT NOT NULL,
                status TEXT NOT NULL,
                message TEXT NOT NULL,
                output TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        self.connection.commit()

    def record(self, result: RemediationResult) -> None:
        self.connection.execute(
            """
            INSERT INTO remediation_audit
            (action_id, incident_id, action, requested_by, status, message, output)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(result.action_id),
                str(result.request.incident_id),
                result.request.action,
                result.request.requested_by,
                result.status.value,
                result.message,
                result.output,
            ),
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

