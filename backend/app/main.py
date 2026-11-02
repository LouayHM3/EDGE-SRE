from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.routes import create_router
from backend.api.state import ApplicationState


def create_app(state: ApplicationState | None = None) -> FastAPI:
    application_state = state or ApplicationState()
    app = FastAPI(title="EDGE-SRE API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_credentials=False,
        allow_methods=["GET"],
        allow_headers=["*"],
    )
    app.include_router(create_router(application_state))
    app.state.edge_sre = application_state
    return app


app = create_app()

