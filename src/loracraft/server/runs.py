"""Training runs: create from the current dataset, queue, execute one at a time, report progress.

Each run owns a directory `projects/<project>/runs/<run>/`. The trainer process writes
`events.jsonl` there; the API serves those events by line offset, so progress survives
server restarts and clients can simply poll.
"""

import json
import logging
import os
import shutil
import sqlite3
import statistics
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..trainer.config import TrainConfig, TrainImage
from . import db
from .datasets import image_path
from .system import load_settings

router = APIRouter(prefix="/api")
logger = logging.getLogger(__name__)


def run_dir(row: sqlite3.Row) -> Path:
    path = db.project_dir(row["project_id"]) / "runs" / str(row["id"])
    path.mkdir(parents=True, exist_ok=True)
    return path


def _run(conn: sqlite3.Connection, run_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Run not found")
    return row


def _read_events(directory: Path, after: int = 0) -> list[dict]:
    file = directory / "events.jsonl"
    if not file.exists():
        return []
    with open(file, encoding="utf-8") as f:
        lines = f.readlines()[after:]
    events = []
    for line in lines:
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            break  # a line still being written
    return events


class _Progress:
    """Progress figures of one run, folded from its event log.

    The UI polls run summaries every few seconds, so each call reads only what the trainer has
    appended since the previous one instead of the whole log.
    """

    def __init__(self) -> None:
        self._offset = 0  # bytes of events.jsonl already folded in
        self._step_seconds: deque[float] = deque(maxlen=50)
        self._figures = {
            "phase": None,
            "step": 0,
            "total_steps": None,
            "steps_per_epoch": None,
            "epoch": 0,
            "loss_avg": None,
            "seconds_per_step": None,
            "cache_done": 0,
            "error": None,
        }

    def read(self, directory: Path) -> dict:
        try:
            with open(directory / "events.jsonl", "rb") as f:
                f.seek(self._offset)
                appended = f.read()
        except OSError:
            appended = b""
        complete = appended.rfind(b"\n") + 1  # a last line still being written waits for the next call
        self._offset += complete
        for line in appended[:complete].splitlines():
            try:
                self._fold(json.loads(line))
            except (ValueError, KeyError):
                continue
        if self._step_seconds:
            # Median of recent steps: robust against the slow first steps while kernels warm up.
            self._figures["seconds_per_step"] = statistics.median(self._step_seconds)
        return dict(self._figures)

    def _fold(self, event: dict) -> None:
        kind = event["type"]
        if kind == "status":
            self._figures["phase"] = event["phase"]
        elif kind == "start":
            self._figures.update(total_steps=event["total_steps"], steps_per_epoch=event["steps_per_epoch"])
        elif kind == "cache":
            self._figures["cache_done"] = event["done"]
        elif kind == "step":
            self._figures.update(step=event["step"], epoch=event["epoch"], loss_avg=event["loss_avg"])
            self._step_seconds.append(event["seconds"])
        elif kind == "error":
            self._figures["error"] = event["message"]


_progress: dict[str, _Progress] = {}  # by run directory
_progress_lock = threading.Lock()


def _summary(row: sqlite3.Row) -> dict:
    """Run row plus the progress figures the UI needs for lists and the status bar."""
    directory = run_dir(row)
    data = dict(row)
    data["config"] = json.loads(row["config"])
    data["num_images"] = len(data["config"].pop("images"))
    with _progress_lock:
        data["progress"] = _progress.setdefault(str(directory), _Progress()).read(directory)
    data["checkpoints"] = sorted(p.name for p in (directory / "checkpoints").glob("*.safetensors"))
    data["samples"] = sorted(p.name for p in (directory / "samples").glob("*.png"))
    return data


def _process_started_at(pid: int) -> float | None:
    """Unix time at which the running process `pid` was created, or None if no such process runs."""
    if sys.platform != "win32":
        try:
            os.kill(pid, 0)
            return Path(f"/proc/{pid}").stat().st_ctime
        except OSError:
            return None

    import ctypes

    kernel32 = ctypes.windll.kernel32
    kernel32.OpenProcess.restype = ctypes.c_void_p
    query_limited_information, synchronize = 0x1000, 0x00100000
    handle = kernel32.OpenProcess(query_limited_information | synchronize, False, pid)
    if not handle:
        return None
    handle = ctypes.c_void_p(handle)
    try:
        if kernel32.WaitForSingleObject(handle, 0) != 0x102:  # anything but WAIT_TIMEOUT: it has exited
            return None
        created, exited, kernel, user = (ctypes.c_ulonglong() for _ in range(4))
        if not kernel32.GetProcessTimes(
            handle, ctypes.byref(created), ctypes.byref(exited), ctypes.byref(kernel), ctypes.byref(user)
        ):
            return None
        return created.value / 1e7 - 11644473600  # FILETIME: 100 ns ticks since 1601
    finally:
        kernel32.CloseHandle(handle)


def trainer_alive(directory: Path) -> bool:
    """Whether the trainer that recorded its pid in `directory` is still running.

    A process created after the pid file was written is something else that got the same pid.
    """
    pid_file = directory / "pid"
    try:
        pid = int(pid_file.read_text())
        written_at = pid_file.stat().st_mtime
    except (OSError, ValueError):
        return False
    started_at = _process_started_at(pid)
    return started_at is not None and started_at <= written_at + 2


# --- Queue -----------------------------------------------------------------


class RunQueue:
    """Runs queued jobs one at a time, each in its own trainer process."""

    def __init__(self) -> None:
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._closing = False

    def start(self) -> None:
        self._closing = False
        self._thread = threading.Thread(target=self._loop, name="run-queue", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._closing = True
        self._wake.set()

    def notify(self) -> None:
        self._wake.set()

    def _loop(self) -> None:
        try:
            self._adopt_orphans()
        except Exception:
            logger.exception("Could not check for trainers left over from a previous server")

        while not self._closing:
            row = None
            try:
                with db.session() as conn:
                    row = conn.execute("SELECT * FROM runs WHERE status = 'queued' ORDER BY id LIMIT 1").fetchone()
                if row is None:
                    self._wake.wait()
                    self._wake.clear()
                    continue
                self._execute(row)
            except Exception:
                # Whatever went wrong with one run, the queue has to keep serving the next ones.
                logger.exception("Run queue error")
                try:
                    if row is not None:
                        self._finalize(row, exit_code=1)
                except Exception:
                    logger.exception("Could not mark run %s as failed", row["id"])
                time.sleep(5)

    def _adopt_orphans(self) -> None:
        # A trainer started by a previous server process may still be working: it does not depend
        # on the server. Wait for it rather than starting a second job on the same GPU.
        with db.session() as conn:
            orphans = conn.execute("SELECT * FROM runs WHERE status = 'running' ORDER BY id").fetchall()
        for row in orphans:
            while trainer_alive(run_dir(row)) and not self._closing:
                time.sleep(2)
            if not self._closing:
                self._finalize(row, exit_code=None)

    def _execute(self, row: sqlite3.Row) -> None:
        directory = run_dir(row)
        with db.session() as conn:
            claimed = conn.execute(
                "UPDATE runs SET status = 'running', started_at = datetime('now') WHERE id = ? AND status = 'queued'",
                (row["id"],),
            ).rowcount
        if not claimed:
            return  # stopped by the user in the moment between being picked and being started

        with open(directory / "trainer.log", "ab") as log:
            process = subprocess.Popen(
                [sys.executable, "-m", "loracraft.trainer", str(directory)],
                stdout=subprocess.DEVNULL,  # events are read from events.jsonl
                stderr=log,
                # Its own process group: Ctrl+C in the server's console must not end the training.
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
                start_new_session=sys.platform != "win32",
            )
            # Recorded here, not only by the trainer once it is up, so that a server restarted
            # during the trainer's slow start still finds it.
            (directory / "pid").write_text(str(process.pid))
            code = process.wait()
        self._finalize(row, code)

    def _finalize(self, row: sqlite3.Row, exit_code: int | None) -> None:
        """Record how a run ended, judged by its own event log."""
        done = next((e for e in reversed(_read_events(run_dir(row))) if e["type"] == "done"), None)
        if done is None or exit_code not in (None, 0):
            status = "failed"
        else:
            status = "stopped" if done["stopped"] else "done"
        with db.session() as conn:
            conn.execute("UPDATE runs SET status = ?, finished_at = datetime('now') WHERE id = ?", (status, row["id"]))


queue = RunQueue()


# --- API -------------------------------------------------------------------


class RunIn(BaseModel):
    name: str = ""
    config: dict  # TrainConfig fields except `images`, which are snapshotted from the dataset


@router.get("/projects/{project_id}/runs")
def list_runs(project_id: int, conn: sqlite3.Connection = Depends(db.get_db)):
    rows = conn.execute("SELECT * FROM runs WHERE project_id = ? ORDER BY id DESC", (project_id,)).fetchall()
    return [_summary(r) for r in rows]


@router.post("/projects/{project_id}/runs")
def create_run(project_id: int, body: RunIn, conn: sqlite3.Connection = Depends(db.get_db)):
    """Snapshot the project's images and captions into a new queued run."""
    images = conn.execute("SELECT * FROM images WHERE project_id = ? ORDER BY id", (project_id,)).fetchall()
    if not images:
        raise HTTPException(400, "The dataset is empty")

    count = conn.execute("SELECT COUNT(*) FROM runs WHERE project_id = ?", (project_id,)).fetchone()[0]
    name = body.name.strip() or f"#{count + 1}"
    try:
        config = TrainConfig(
            **{k: v for k, v in body.config.items() if k != "images"},
            images=[TrainImage(path=str(image_path(i)), caption=i["caption"]) for i in images],
        )
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    if not Path(config.base_model).is_file():
        raise HTTPException(400, f"Base model not found: {config.base_model}")

    cur = conn.execute(
        "INSERT INTO runs (project_id, name, config) VALUES (?, ?, ?)",
        (project_id, name, config.model_dump_json()),
    )
    row = _run(conn, cur.lastrowid)
    (run_dir(row) / "config.json").write_text(config.model_dump_json(indent=1), encoding="utf-8")
    conn.commit()
    queue.notify()
    return _summary(row)


@router.get("/runs/{run_id}")
def get_run(run_id: int, conn: sqlite3.Connection = Depends(db.get_db)):
    return _summary(_run(conn, run_id))


@router.get("/runs/{run_id}/events")
def get_events(run_id: int, after: int = 0, conn: sqlite3.Connection = Depends(db.get_db)):
    """Events from line offset `after`. Poll with `after` set to the number of events already received."""
    row = _run(conn, run_id)
    return {"status": row["status"], "events": _read_events(run_dir(row), after)}


@router.post("/runs/{run_id}/stop")
def stop_run(run_id: int, conn: sqlite3.Connection = Depends(db.get_db)):
    row = _run(conn, run_id)
    if row["status"] == "queued":
        conn.execute("UPDATE runs SET status = 'stopped', finished_at = datetime('now') WHERE id = ?", (run_id,))
    elif row["status"] == "running":
        (run_dir(row) / "stop").touch()
    return {"ok": True}


class RunPatch(BaseModel):
    name: str | None = None
    notes: str | None = None
    rating: int | None = None
    best_checkpoint: str | None = None


@router.patch("/runs/{run_id}")
def update_run(run_id: int, body: RunPatch, conn: sqlite3.Connection = Depends(db.get_db)):
    _run(conn, run_id)
    for field, value in body.model_dump(exclude_none=True).items():
        conn.execute(f"UPDATE runs SET {field} = ? WHERE id = ?", (value, run_id))
    return _summary(_run(conn, run_id))


@router.delete("/runs/{run_id}")
def delete_run(run_id: int, conn: sqlite3.Connection = Depends(db.get_db)):
    """Remove a finished run together with its checkpoints and preview images."""
    row = _run(conn, run_id)
    if row["status"] in ("queued", "running"):
        raise HTTPException(409, "这次训练还在进行或排队，先停止它")
    directory = run_dir(row)
    conn.execute("DELETE FROM runs WHERE id = ?", (run_id,))
    conn.commit()  # row first: leftover files are harmless, a row without its files is not
    shutil.rmtree(directory, ignore_errors=True)
    with _progress_lock:
        _progress.pop(str(directory), None)
    return {"ok": True}


@router.get("/runs/{run_id}/samples/{name}")
def get_sample(run_id: int, name: str, conn: sqlite3.Connection = Depends(db.get_db)):
    file = run_dir(_run(conn, run_id)) / "samples" / Path(name).name
    if not file.is_file():
        raise HTTPException(404, "Sample not found")
    return FileResponse(file)


class ExportIn(BaseModel):
    checkpoint: str


@router.post("/runs/{run_id}/export")
def export_checkpoint(run_id: int, body: ExportIn, conn: sqlite3.Connection = Depends(db.get_db)):
    """Copy a checkpoint into the configured export folder under a readable name."""
    row = _run(conn, run_id)
    source = run_dir(row) / "checkpoints" / Path(body.checkpoint).name
    if not source.is_file():
        raise HTTPException(404, "Checkpoint not found")

    export_dir = load_settings(conn).export_dir
    if not export_dir or not Path(export_dir).is_dir():
        raise HTTPException(400, "Set an existing export folder in settings first")

    project = conn.execute("SELECT name FROM projects WHERE id = ?", (row["project_id"],)).fetchone()
    epoch = source.stem.rsplit("-", 1)[-1].lstrip("0") or "0"
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in f"{project['name']}_{row['name']}_e{epoch}")
    target = Path(export_dir) / f"{safe}.safetensors"
    shutil.copyfile(source, target)
    return {"path": str(target)}
