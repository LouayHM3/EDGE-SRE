from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .models import Event


class EventStore:
    def __init__(self, database_path: str | Path = "edge-sre.db") -> None:
        self.connection = sqlite3.connect(database_path)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                event_id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                host_id TEXT NOT NULL,
                component TEXT NOT NULL,
                severity TEXT NOT NULL,
                event_type TEXT NOT NULL,
                observed_value TEXT NOT NULL,
                threshold TEXT,
                description TEXT NOT NULL,
                related_service TEXT,
                correlation_key TEXT
            )
            """
        )
        self.connection.commit()

    def save(self, event: Event) -> bool:
        cursor = self.connection.execute(
            """
            INSERT OR IGNORE INTO events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(event.event_id), event.timestamp.isoformat(), event.host_id,
                event.component, event.severity.value, event.event_type.value,
                json.dumps(event.observed_value), json.dumps(event.threshold),
                event.description, event.related_service, event.correlation_key,
            ),
        )
        self.connection.commit()
        return cursor.rowcount == 1

    def close(self) -> None:
        self.connection.close()

