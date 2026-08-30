from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api.routes import router
from backend.app.config import env_list

APP_VERSION = "0.1.0"

app = FastAPI(title="心理原探杯 API", version=APP_VERSION)
app.add_middleware(
    CORSMiddleware,
    allow_origins=env_list("CORS_ORIGINS", ("http://localhost:5173", "http://127.0.0.1:5173")),
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
def ready() -> dict[str, str | int]:
    """Report whether the runtime has loaded the expected twenty rubrics.

    ``/health`` stays a cheap liveness check for existing clients.  This
    additive readiness endpoint gives a reverse proxy or process supervisor a
    meaningful signal without exposing filesystem paths or configuration.
    """

    from backend.app.api.routes import RUBRICS

    rubric_count = len(RUBRICS)
    if rubric_count != 20:
        raise HTTPException(status_code=503, detail="rubric catalog is incomplete")
    return {"status": "ready", "rubrics": rubric_count, "version": APP_VERSION}
