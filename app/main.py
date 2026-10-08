from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import APP_ROOT, REPO_ROOT, DATA_ROOT
from app.git_sync import start_sync_worker, stop_sync_worker
from app.routers.entries import router as entries_router
from app.web import router as web_router


def load_env() -> None:
    env_path = APP_ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        if value:
            os.environ.setdefault(key.strip(), value)


load_env()
if "REPO_ROOT" not in os.environ:
    os.environ["REPO_ROOT"] = str(REPO_ROOT)

@asynccontextmanager
async def lifespan(app: FastAPI):
    start_sync_worker()
    yield
    stop_sync_worker()


app = FastAPI(title="Media Diary", version="1.1.0", lifespan=lifespan)
app.include_router(entries_router)
app.include_router(web_router)

static_dir = APP_ROOT / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
def ready() -> dict[str, str]:
    from fastapi import HTTPException
    if not DATA_ROOT.is_dir() or not os.access(DATA_ROOT, os.R_OK | os.W_OK):
        raise HTTPException(status_code=503, detail="Diary storage unavailable")
    for name in ("movies.csv", "books.csv", "tv.csv", "movies_watchlist.csv", "books_watchlist.csv", "tv_watchlist.csv"):
        path = DATA_ROOT / name
        if not path.is_file() or not os.access(path, os.R_OK | os.W_OK):
            raise HTTPException(status_code=503, detail="Diary file unavailable")
    return {"status": "ready"}
