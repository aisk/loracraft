"""FastAPI application: the JSON API under /api plus the built web UI."""

import sys
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from . import datasets, db, runs, system, tagging

# Built by `npm run build` in web/ and shipped inside the package.
WEB_DIST = Path(__file__).resolve().parents[1] / "web_dist"
LOCAL_HOSTS = {"127.0.0.1", "localhost"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init()
    runs.queue.start()
    yield
    runs.queue.stop()


app = FastAPI(title="LoraCraft", lifespan=lifespan)


@app.middleware("http")
async def local_only(request: Request, call_next):
    """Serve this machine's own pages only.

    The API has no login, so a web page elsewhere must not reach it: neither by pointing its own
    domain at 127.0.0.1 (a foreign Host header) nor by posting across origins (a foreign Origin).
    """
    origin = request.headers.get("origin")
    if request.url.hostname not in LOCAL_HOSTS or (origin and urlsplit(origin).hostname not in LOCAL_HOSTS):
        return PlainTextResponse("Forbidden", status_code=403)
    return await call_next(request)


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
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser(prog="loracraft", description="LoRA training workbench")
    parser.add_argument("--port", type=int, default=8600, help="port to listen on (default: %(default)s)")
    parser.add_argument(
        "--window", action="store_true", help="open in a window of its own instead of serving a browser"
    )
    args = parser.parse_args()

    if not WEB_DIST.is_dir():
        print(f"The web UI is not built ({WEB_DIST} is missing): only the API will be served.", file=sys.stderr)
    print(f"Data directory: {db.workspace()}")
    if args.window:
        run_in_window(args.port)
    else:
        uvicorn.run("loracraft.server.app:app", host="127.0.0.1", port=args.port)


def run_in_window(port: int) -> None:
    """Serve from a background thread and show the UI in the system's web view until it is closed.

    Closing the window stops the server only. A training run in progress is its own process and
    carries on; the next start picks it up, and starts whatever was still queued.
    """
    import threading
    import time

    import uvicorn

    try:
        import webview
    except ImportError:
        sys.exit('--window needs pywebview: pip install "loracraft[app]"')

    server = uvicorn.Server(uvicorn.Config("loracraft.server.app:app", host="127.0.0.1", port=port))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        if not thread.is_alive():
            sys.exit(1)  # the server could not start, e.g. the port is taken; it has said why
        time.sleep(0.05)

    webview.create_window("LoraCraft", f"http://127.0.0.1:{port}", width=1440, height=900, min_size=(960, 600))
    webview.start()  # returns when the window is closed
    server.should_exit = True
    thread.join()
