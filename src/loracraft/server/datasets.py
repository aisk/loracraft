"""Projects and their dataset images: import, captions, tag operations, thumbnails."""

import hashlib
import shutil
import sqlite3
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import FileResponse
from PIL import Image, ImageOps
from pydantic import BaseModel

from ..imaging import to_rgb
from . import db

router = APIRouter(prefix="/api")

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
THUMB_SIZE = 384


# --- Tag helpers -----------------------------------------------------------


def split_tags(caption: str) -> list[str]:
    return [t.strip() for t in caption.split(",") if t.strip()]


def join_tags(tags: list[str]) -> str:
    seen = set()
    unique = [t for t in tags if not (t in seen or seen.add(t))]
    return ", ".join(unique)


# --- Projects --------------------------------------------------------------


class ProjectIn(BaseModel):
    name: str
    kind: str = "character"
    trigger: str = ""
    notes: str = ""


class ProjectPatch(BaseModel):
    name: str | None = None
    kind: str | None = None
    trigger: str | None = None
    notes: str | None = None


def _project(conn: sqlite3.Connection, project_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Project not found")
    return row


@router.get("/projects")
def list_projects(conn: sqlite3.Connection = Depends(db.get_db)):
    rows = conn.execute(
        """SELECT p.*,
                  (SELECT COUNT(*) FROM images i WHERE i.project_id = p.id) AS image_count,
                  (SELECT COUNT(*) FROM runs r WHERE r.project_id = p.id) AS run_count,
                  (SELECT COUNT(*) FROM images i WHERE i.project_id = p.id AND i.caption = '') AS uncaptioned_count,
                  (SELECT COUNT(*) FROM runs r WHERE r.project_id = p.id AND r.status IN ('queued', 'running'))
                      AS active_runs,
                  (SELECT id FROM images i WHERE i.project_id = p.id ORDER BY id LIMIT 1) AS cover_image_id
           FROM projects p ORDER BY p.id DESC"""
    ).fetchall()
    return [dict(r) for r in rows]


@router.post("/projects")
def create_project(body: ProjectIn, conn: sqlite3.Connection = Depends(db.get_db)):
    cur = conn.execute(
        "INSERT INTO projects (name, kind, trigger, notes) VALUES (?, ?, ?, ?)",
        (body.name, body.kind, body.trigger, body.notes),
    )
    db.project_dir(cur.lastrowid)
    return dict(_project(conn, cur.lastrowid))


@router.get("/projects/{project_id}")
def get_project(project_id: int, conn: sqlite3.Connection = Depends(db.get_db)):
    return dict(_project(conn, project_id))


@router.patch("/projects/{project_id}")
def update_project(project_id: int, body: ProjectPatch, conn: sqlite3.Connection = Depends(db.get_db)):
    _project(conn, project_id)
    for field, value in body.model_dump(exclude_none=True).items():
        conn.execute(f"UPDATE projects SET {field} = ? WHERE id = ?", (value, project_id))
    return dict(_project(conn, project_id))


@router.delete("/projects/{project_id}")
def delete_project(project_id: int, conn: sqlite3.Connection = Depends(db.get_db)):
    _project(conn, project_id)
    _refuse_while_training(conn, project_id)
    conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    shutil.rmtree(db.workspace() / "projects" / str(project_id), ignore_errors=True)
    return {"ok": True}


def _refuse_while_training(conn: sqlite3.Connection, project_id: int) -> None:
    """A queued or running training reads the project's image files; they must not vanish under it."""
    active = conn.execute(
        "SELECT 1 FROM runs WHERE project_id = ? AND status IN ('queued', 'running')", (project_id,)
    ).fetchone()
    if active:
        raise HTTPException(409, "这个项目有训练正在进行或排队，先等它结束或停止它")


# --- Images ----------------------------------------------------------------


def _image(conn: sqlite3.Connection, image_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM images WHERE id = ?", (image_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Image not found")
    return row


def image_path(row: sqlite3.Row) -> Path:
    return db.project_dir(row["project_id"]) / "images" / row["filename"]


def _add_image(conn: sqlite3.Connection, project_id: int, name: str, data: bytes, caption: str) -> dict | None:
    """Store one image in the project. Returns None when the same file is already there."""
    digest = hashlib.sha256(data).hexdigest()
    if conn.execute("SELECT 1 FROM images WHERE project_id = ? AND sha256 = ?", (project_id, digest)).fetchone():
        return None

    images_dir = db.project_dir(project_id) / "images"
    stem, suffix = Path(name).stem, Path(name).suffix.lower()
    target = images_dir / f"{stem}{suffix}"
    counter = 1
    while target.exists():
        target = images_dir / f"{stem}_{counter}{suffix}"
        counter += 1
    target.write_bytes(data)

    try:
        with Image.open(target) as image:
            width, height = ImageOps.exif_transpose(image).size
    except Exception:
        target.unlink(missing_ok=True)
        raise HTTPException(400, f"Not a readable image: {name}") from None

    cur = conn.execute(
        "INSERT INTO images (project_id, filename, width, height, sha256, caption) VALUES (?, ?, ?, ?, ?, ?)",
        (project_id, target.name, width, height, digest, join_tags(split_tags(caption))),
    )
    return dict(_image(conn, cur.lastrowid))


class _ImportResult:
    """Outcome of importing several files. Each file is committed on its own, so a file that fails
    later never leaves earlier ones on disk without a database row."""

    def __init__(self) -> None:
        self.added: list[dict] = []
        self.duplicates = 0
        self.unreadable: list[str] = []

    def add(self, conn: sqlite3.Connection, project_id: int, name: str, data: bytes, caption: str) -> None:
        try:
            image = _add_image(conn, project_id, name, data, caption)
        except HTTPException:
            self.unreadable.append(name)
            return
        conn.commit()
        if image is None:
            self.duplicates += 1
        else:
            self.added.append(image)

    def as_dict(self) -> dict:
        return {"added": self.added, "skipped_duplicates": self.duplicates, "unreadable": self.unreadable}


@router.get("/projects/{project_id}/images")
def list_images(project_id: int, conn: sqlite3.Connection = Depends(db.get_db)):
    _project(conn, project_id)
    rows = conn.execute("SELECT * FROM images WHERE project_id = ? ORDER BY id", (project_id,)).fetchall()
    return [dict(r) for r in rows]


@router.post("/projects/{project_id}/images")
def upload_images(project_id: int, files: list[UploadFile], conn: sqlite3.Connection = Depends(db.get_db)):
    """Upload images. A .txt file with the same stem as an image is taken as its caption."""
    # Not async: decoding and storing images is blocking work, which belongs in the thread pool.
    _project(conn, project_id)
    named = [(Path(f.filename).name, f) for f in files if f.filename]
    captions = {
        Path(name).stem: f.file.read().decode("utf-8", errors="replace")
        for name, f in named
        if Path(name).suffix.lower() == ".txt"
    }

    result = _ImportResult()
    for name, f in named:
        if Path(name).suffix.lower() in IMAGE_SUFFIXES:
            # One file in memory at a time; the rest stay in the upload's temporary files.
            result.add(conn, project_id, name, f.file.read(), captions.get(Path(name).stem, ""))
    return result.as_dict()


class ImportFolder(BaseModel):
    path: str


@router.post("/projects/{project_id}/images/import")
def import_folder(project_id: int, body: ImportFolder, conn: sqlite3.Connection = Depends(db.get_db)):
    """Copy images (and sidecar .txt captions) from a folder on this machine into the project."""
    _project(conn, project_id)
    folder = Path(body.path)
    if not folder.is_dir():
        raise HTTPException(400, f"Not a folder: {body.path}")

    result = _ImportResult()
    for file in sorted(folder.iterdir()):
        if file.suffix.lower() not in IMAGE_SUFFIXES or not file.is_file():
            continue
        sidecar = file.with_suffix(".txt")
        caption = sidecar.read_text(encoding="utf-8", errors="replace") if sidecar.exists() else ""
        result.add(conn, project_id, file.name, file.read_bytes(), caption)
    return result.as_dict()


class ImagePatch(BaseModel):
    caption: str


@router.patch("/images/{image_id}")
def update_image(image_id: int, body: ImagePatch, conn: sqlite3.Connection = Depends(db.get_db)):
    _image(conn, image_id)
    conn.execute("UPDATE images SET caption = ? WHERE id = ?", (join_tags(split_tags(body.caption)), image_id))
    return dict(_image(conn, image_id))


class DeleteImages(BaseModel):
    image_ids: list[int]


@router.post("/images/delete")
def delete_images(body: DeleteImages, conn: sqlite3.Connection = Depends(db.get_db)):
    marks = ",".join("?" * len(body.image_ids))
    rows = conn.execute(f"SELECT * FROM images WHERE id IN ({marks})", body.image_ids).fetchall()
    for project_id in {row["project_id"] for row in rows}:
        _refuse_while_training(conn, project_id)
    conn.execute(f"DELETE FROM images WHERE id IN ({marks})", body.image_ids)
    conn.commit()  # rows first: a leftover file is harmless, a row without its file is not
    for row in rows:
        image_path(row).unlink(missing_ok=True)
        _thumb_path(row).unlink(missing_ok=True)
    return {"ok": True}


class TagEdit(BaseModel):
    image_ids: list[int]
    add: list[str] = []
    add_position: str = "end"  # start | end
    remove: list[str] = []
    replace: dict[str, str] = {}


@router.post("/tags/edit")
def edit_tags(body: TagEdit, conn: sqlite3.Connection = Depends(db.get_db)):
    """Batch tag edit over a set of images: replace first, then remove, then add."""
    updated = []
    for image_id in body.image_ids:
        row = _image(conn, image_id)
        tags = [body.replace.get(t, t) for t in split_tags(row["caption"])]
        tags = [t for t in tags if t not in body.remove]
        new = [t.strip() for t in body.add if t.strip() and t.strip() not in tags]
        tags = new + tags if body.add_position == "start" else tags + new
        conn.execute("UPDATE images SET caption = ? WHERE id = ?", (join_tags(tags), image_id))
        updated.append(dict(_image(conn, image_id)))
    return updated


# --- Files -----------------------------------------------------------------


def _thumb_path(row: sqlite3.Row) -> Path:
    return db.project_dir(row["project_id"]) / "thumbs" / f"{row['sha256'][:16]}.webp"


@router.get("/images/{image_id}/thumb")
def get_thumb(image_id: int, conn: sqlite3.Connection = Depends(db.get_db)):
    row = _image(conn, image_id)
    thumb = _thumb_path(row)
    if not thumb.exists():
        # Written under another name first: a request arriving meanwhile must not be served half a file.
        partial = thumb.with_name(f"{thumb.name}.{uuid.uuid4().hex}.tmp")
        with Image.open(image_path(row)) as image:
            image = to_rgb(image)
            image.thumbnail((THUMB_SIZE, THUMB_SIZE), Image.LANCZOS)
            image.save(partial, "WEBP", quality=82)
        try:
            partial.replace(thumb)
        except OSError:  # another request finished the same thumbnail first
            partial.unlink(missing_ok=True)
    return FileResponse(thumb, media_type="image/webp", headers={"Cache-Control": "max-age=31536000, immutable"})


@router.get("/images/{image_id}/file")
def get_file(image_id: int, conn: sqlite3.Connection = Depends(db.get_db)):
    return FileResponse(image_path(_image(conn, image_id)))
