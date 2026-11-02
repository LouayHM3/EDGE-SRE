from __future__ import annotations

import asyncio
import json
import logging
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from typing import Any

from pydantic import ValidationError

from backend.events.models import Event
from backend.incidents.models import Incident

from .schemas import Diagnosis

logger = logging.getLogger(__name__)
Transport = Callable[[bytes, float], bytes]


class OllamaUnavailable(RuntimeError):
    """Raised when the local Ollama provider cannot return a valid response."""


class OllamaDiagnosticProvider:
    def __init__(
        self,
        model: str = "llama3.2",
        endpoint: str = "http://127.0.0.1:11434/api/generate",
        timeout_seconds: float = 30.0,
        max_concurrency: int = 1,
        transport: Transport | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if max_concurrency <= 0:
            raise ValueError("max_concurrency must be positive")
        self.model = model
        self.endpoint = endpoint
        self.timeout_seconds = timeout_seconds
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._transport = transport or self._request

    async def diagnose(self, incident: Incident, events: Sequence[Event]) -> Diagnosis:
        if not events:
            raise ValueError(f"No evidence found for incident {incident.incident_id}")
        payload = self._payload(incident, events)
        async with self._semaphore:
            try:
                raw_response = await asyncio.wait_for(
                    asyncio.to_thread(self._transport, payload, self.timeout_seconds),
                    timeout=self.timeout_seconds + 1,
                )
                response = json.loads(raw_response)
                model_output = response.get("response")
                if not isinstance(model_output, str):
                    raise OllamaUnavailable("Ollama response did not contain text output")
                diagnosis = Diagnosis.model_validate(json.loads(model_output))
                if diagnosis.incident_id != incident.incident_id:
                    raise OllamaUnavailable("Ollama returned a diagnosis for another incident")
                return diagnosis
            except (
                OSError,
                TimeoutError,
                asyncio.TimeoutError,
                urllib.error.URLError,
                json.JSONDecodeError,
                ValidationError,
                OllamaUnavailable,
            ) as exc:
                raise OllamaUnavailable(f"Local Ollama diagnosis failed: {exc}") from exc

    def _payload(self, incident: Incident, events: Sequence[Event]) -> bytes:
        evidence = [
            {
                "event_id": str(event.event_id),
                "component": event.component,
                "severity": event.severity.value,
                "event_type": event.event_type.value,
                "observed_value": event.observed_value,
                "threshold": event.threshold,
                "description": event.description,
                "related_service": event.related_service,
            }
            for event in events
            if event.event_id in incident.event_ids
        ]
        prompt = (
            "Return only valid JSON matching this schema: "
            '{"incident_id":"UUID","summary":"string","probable_root_causes":["string"],'
            '"evidence":[{"source":"string","observation":"string"}],'
            '"severity":"info|warning|high|critical","confidence":0.0,'
            '"recommended_actions":[{"action":"string","rationale":"string","risk":"low"}],'
            '"limitations":["string"]}. '
            f"Incident: {incident.model_dump_json()}. Evidence: {json.dumps(evidence)}"
        )
        return json.dumps({
            "model": self.model,
            "prompt": prompt,
            "format": "json",
            "stream": False,
        }).encode("utf-8")

    def _request(self, payload: bytes, timeout: float) -> bytes:
        request = urllib.request.Request(
            self.endpoint,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()


class FallbackDiagnosticProvider:
    def __init__(self, primary: OllamaDiagnosticProvider, fallback: Any) -> None:
        self.primary = primary
        self.fallback = fallback

    async def diagnose(self, incident: Incident, events: Sequence[Event]) -> Diagnosis:
        try:
            return await self.primary.diagnose(incident, events)
        except OllamaUnavailable as exc:
            logger.warning("Using deterministic diagnosis fallback: %s", exc)
            diagnosis = self.fallback.diagnose(incident, events)
            diagnosis.limitations.append("Ollama was unavailable; deterministic fallback was used.")
            return diagnosis
