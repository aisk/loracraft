"""Settings and base model discovery."""

import functools
import importlib.util
import json
import sqlite3
import struct
import subprocess
import sys
from pathlib import Path

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from . import db

router = APIRouter(prefix="/api")

MAX_HEADER_BYTES = 100 * 2**20  # real headers are well under 1 MB; a larger figure means a damaged file


class Settings(BaseModel):
    model_dirs: list[str] = []  # folders scanned for base model checkpoints
    export_dir: str = ""  # where "export" copies a finished LoRA, e.g. ComfyUI's models/loras
    # Vision model for auto-captioning: any OpenAI-compatible endpoint, e.g. http://localhost:11434/v1
    tagger_base_url: str = ""
    tagger_api_key: str = ""
    tagger_model: str = ""


def load_settings(conn: sqlite3.Connection) -> Settings:
    row = conn.execute("SELECT value FROM settings WHERE key = 'app'").fetchone()
    return Settings.model_validate_json(row["value"]) if row else Settings()


@router.get("/settings")
def get_settings(conn: sqlite3.Connection = Depends(db.get_db)) -> Settings:
    return load_settings(conn)


@router.put("/settings")
def put_settings(body: Settings, conn: sqlite3.Connection = Depends(db.get_db)) -> Settings:
    body.model_dirs = [d.strip() for d in body.model_dirs if d.strip()]
    body.export_dir = body.export_dir.strip()
    conn.execute(
        "INSERT INTO settings (key, value) VALUES ('app', ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (body.model_dump_json(),),
    )
    return body


@functools.cache
def trainer_status() -> dict:
    """Whether this Python environment can train: PyTorch must be installed and see a GPU.

    Which PyTorch build is right depends on the GPU, so the user installs it; the usual mistake is
    ending up with the CPU-only build. Asked of a child process, because importing torch is slow
    and the server has no other use for it. Cached: a new installation needs a restart anyway.
    """
    status = {"ready": False, "problem": "missing", "torch_version": "", "python": sys.executable}
    if importlib.util.find_spec("torch") is None:
        return status
    probe = "import torch; print(torch.__version__); print(torch.cuda.is_available())"
    try:
        out = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        return status | {"problem": "broken"}
    lines = out.stdout.split()
    if out.returncode != 0 or len(lines) != 2:
        return status | {"problem": "broken"}  # installed, but the import itself fails
    if lines[1] != "True":
        return status | {"problem": "no_gpu", "torch_version": lines[0]}
    return status | {"ready": True, "problem": None, "torch_version": lines[0]}


@router.get("/trainer")
def get_trainer_status():
    return trainer_status()


def read_safetensors_header(path: Path) -> dict:
    """The JSON header of a .safetensors file: tensor names and metadata, without loading weights."""
    with open(path, "rb") as f:
        (length,) = struct.unpack("<Q", f.read(8))
        if length > MAX_HEADER_BYTES:
            raise ValueError(f"Implausible safetensors header length: {length}")
        return json.loads(f.read(length))


def inspect_checkpoint(path: Path) -> dict:
    """Decide whether a file is an SDXL checkpoint and whether it is a v-prediction model."""
    try:
        header = read_safetensors_header(path)
    except (OSError, ValueError, struct.error):
        return {"is_sdxl": False, "v_prediction": False, "zero_terminal_snr": False}
    # SDXL has a second text encoder under conditioner.embedders.1; v-pred models carry marker keys.
    is_sdxl = any(k.startswith("conditioner.embedders.1.") for k in header)
    return {"is_sdxl": is_sdxl, "v_prediction": "v_pred" in header, "zero_terminal_snr": "ztsnr" in header}


@router.get("/models")
def list_models(conn: sqlite3.Connection = Depends(db.get_db)):
    """SDXL checkpoints found in the configured model folders."""
    models = []
    missing_dirs = []
    for directory in load_settings(conn).model_dirs:
        root = Path(directory)
        if not root.is_dir():
            missing_dirs.append(directory)
            continue
        for file in sorted(root.rglob("*.safetensors")):
            info = inspect_checkpoint(file)
            if info["is_sdxl"]:
                models.append(
                    {"path": str(file), "name": file.stem, "size_gb": round(file.stat().st_size / 2**30, 2), **info}
                )
    return {"models": models, "missing_dirs": missing_dirs}
