from __future__ import annotations

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from .state import ApplicationState


def create_router(state: ApplicationState) -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "edge-sre"}

    @router.get("/overview")
    async def overview() -> dict:
        active = list(state.incidents.active())
        severity = {level: 0 for level in ("info", "warning", "high", "critical")}
        for incident in active:
            severity[incident.severity.value] += 1
        return {
            "host_id": state.latest_snapshot.host_id if state.latest_snapshot else None,
            "active_incidents": len(active),
            "severity_distribution": severity,
            "event_count": len(state.events),
            "latest_snapshot": state.latest_snapshot.model_dump(mode="json") if state.latest_snapshot else None,
        }

    @router.get("/metrics")
    async def metrics() -> dict:
        if state.latest_snapshot is None:
            return {"snapshot": None}
        return {"snapshot": state.latest_snapshot.model_dump(mode="json")}

    @router.get("/incidents")
    async def incidents(active_only: bool = False) -> list[dict]:
        values = state.incidents.active() if active_only else state.incidents.incidents.values()
        return [incident.model_dump(mode="json") for incident in values]

    @router.get("/incidents/{incident_id}")
    async def incident(incident_id: str) -> dict:
        for value in state.incidents.incidents.values():
            if str(value.incident_id) == incident_id:
                return value.model_dump(mode="json")
        raise HTTPException(status_code=404, detail="Incident not found")

    @router.get("/events")
    async def events(limit: int = 100) -> list[dict]:
        if not 1 <= limit <= 1000:
            raise HTTPException(status_code=400, detail="limit must be between 1 and 1000")
        return [event.model_dump(mode="json") for event in state.events[-limit:]]

    @router.websocket("/ws")
    async def websocket(websocket: WebSocket) -> None:
        await websocket.accept()
        queue = state.subscribe()
        try:
            await websocket.send_json({"type": "connected"})
            while True:
                await websocket.send_json(await queue.get())
        except WebSocketDisconnect:
            pass
        finally:
            state.unsubscribe(queue)

    return router
