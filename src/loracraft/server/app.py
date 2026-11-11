"""FastAPI application: the JSON API under /api plus the built web UI."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import datasets, db, runs, system, tagging

WEB_DIST = Path(__file__).resolve().parents[3] / "web" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init()
    runs.queue.start()
    yield
    runs.queue.stop()


app = FastAPI(title="LoraCraft", lifespan=lifespan)
app.include_router(datasets.router)
app.include_router(runs.router)
app.include_router(system.router)
app.include_router(tagging.router)

if WEB_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        """Serve the single-page app for every non-API route."""
        if path.startswith("api/"):
            raise HTTPException(404, "Not found")
        # The path comes from the URL: never let it leave the build directory ("..", absolute paths).
        file = (WEB_DIST / path).resolve()
        inside = file.is_relative_to(WEB_DIST)
        return FileResponse(file if path and inside and file.is_file() else WEB_DIST / "index.html")


def main() -> None:
    import uvicorn

    uvicorn.run("loracraft.server.app:app", host="127.0.0.1", port=8600)
