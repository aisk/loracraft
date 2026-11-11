"""Automatic captioning with a vision LLM.

Results are stored as suggestions and never overwrite a caption until the user accepts them.
Any OpenAI-compatible chat completions endpoint works: hosted APIs, OpenRouter, or a local
server such as Ollama or LM Studio.
"""

import base64
import csv
import difflib
import io
import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache

import httpx
from fastapi import APIRouter, Depends, HTTPException
from PIL import Image
from pydantic import BaseModel

from ..imaging import to_rgb
from . import db
from .datasets import image_path, join_tags, split_tags
from .system import load_settings
from .tagging_prompt import CATEGORIES, TaggingProfile, build_prompt

router = APIRouter(prefix="/api")

MAX_IMAGE_SIDE = 1024
PARALLEL_REQUESTS = 3


def normalize_tag(tag: str) -> str:
    return " ".join(tag.strip().lower().replace("_", " ").split())


# --- Tag dictionary --------------------------------------------------------


def dictionary() -> frozenset[str]:
    """Known tags from every CSV in `<workspace>/dictionaries/` (first column is the tag).

    Compatible with the danbooru.csv files used by tag-autocomplete extensions.
    Empty when no dictionary is installed, in which case validation is skipped.
    """
    files = sorted((db.workspace() / "dictionaries").glob("*.csv"))
    # Keyed on the files and their modification times, so dropping in a dictionary takes effect at once.
    return _load_dictionary(tuple((str(f), f.stat().st_mtime) for f in files))


@lru_cache(maxsize=1)
def _load_dictionary(files: tuple[tuple[str, float], ...]) -> frozenset[str]:
    tags = set()
    for path, _ in files:
        with open(path, encoding="utf-8", errors="replace", newline="") as f:
            for row in csv.reader(f):
                if row:
                    tags.add(normalize_tag(row[0]))
    return frozenset(tags)


def check_against_dictionary(tag: str) -> tuple[str, dict | None]:
    """Return the tag to use and, when it was not a known tag, an issue describing what happened."""
    known = dictionary()
    if not known or tag in known:
        return tag, None
    close = _closest_known(tag, known)
    if close:
        return close, {"tag": close, "kind": "corrected", "original": tag}
    return tag, {"tag": tag, "kind": "unknown"}


@lru_cache(maxsize=4096)
def _closest_known(tag: str, known: frozenset[str]) -> str | None:
    # Comparing against a whole Danbooru dictionary takes about 0.1 s, and models repeat their mistakes.
    close = difflib.get_close_matches(tag, known, n=1, cutoff=0.88)
    return close[0] if close else None


# --- Turning a model reply into a caption ------------------------------------


def parse_reply(text: str) -> dict:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError(f"The model did not answer in the requested format: {text.strip()[:200]}")
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        raise ValueError(f"The model's answer was not valid JSON: {text.strip()[:200]}") from None


def build_suggestion(reply: dict, profile: TaggingProfile, trigger: str) -> dict:
    """Apply the profile's rules to a parsed reply. Returns caption, grouped tags and issues."""
    sentence = str(reply.get("caption", "")).strip()
    if profile.format == "natural":
        caption = f"{trigger}, {sentence}" if trigger else sentence
        return {"caption": caption, "groups": {}, "issues": []}

    banned = {normalize_tag(t) for t in profile.banned_tags}
    fixed = {normalize_tag(t) for t in profile.fixed_traits} if profile.goal == "character" else set()
    preferred = {normalize_tag(t) for t in profile.preferred_tags}

    raw = reply.get("tags", {})
    if isinstance(raw, list):  # some models ignore the grouping
        raw = {"subject": raw}

    groups: dict[str, list[str]] = {}
    issues: list[dict] = []
    seen = {normalize_tag(trigger)} if trigger else set()
    for category in CATEGORIES:
        kept = []
        items = raw.get(category) or []
        for item in [items] if isinstance(items, str) else items:
            tag = normalize_tag(str(item))
            if not tag or tag in seen:
                continue
            # Spelling is corrected before the rules are applied, so that a misspelt banned tag or
            # fixed trait is still caught.
            correction = None
            if tag not in preferred and tag not in banned and tag not in fixed:
                tag, correction = check_against_dictionary(tag)
                if tag in seen:
                    continue
            if tag in banned:
                issues.append({"tag": tag, "kind": "banned"})
                continue
            if tag in fixed:
                issues.append({"tag": tag, "kind": "fixed_trait"})
                continue
            if profile.preferred_only and preferred and tag not in preferred:
                issues.append({"tag": tag, "kind": "not_in_vocabulary"})
                continue
            if correction:
                issues.append(correction)
            seen.add(tag)
            kept.append(tag)
        if kept:
            groups[category] = kept

    tags = ([trigger] if trigger else []) + [t for category in CATEGORIES for t in groups.get(category, [])]
    caption = join_tags(tags)
    if profile.format == "mixed" and sentence:
        caption = f"{caption}, {sentence}"
    return {"caption": caption, "groups": groups, "issues": issues}


# --- Calling the model -------------------------------------------------------


def encode_image(path) -> str:
    with Image.open(path) as image:
        image = to_rgb(image)
        image.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE), Image.LANCZOS)
        buffer = io.BytesIO()
        image.save(buffer, "JPEG", quality=90)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode()


def ask_model(client: httpx.Client, model: str, prompt: str, data_url: str) -> str:
    response = client.post(
        "chat/completions",
        json={
            "model": model,
            "temperature": 0.2,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }
            ],
        },
    )
    if response.status_code >= 400:
        raise ValueError(f"The model service answered {response.status_code}: {response.text[:300]}")
    message = response.json()["choices"][0]["message"]
    content = message.get("content") or ""
    if not content.strip():
        raise ValueError(f"The model returned no text{': ' + message['refusal'] if message.get('refusal') else ''}")
    return content


# --- Jobs --------------------------------------------------------------------


class Job:
    def __init__(self, total: int):
        self.total = total
        self.done = 0
        self.errors: list[dict] = []
        self.cancelled = False
        self.running = True

    def snapshot(self) -> dict:
        return {"total": self.total, "done": self.done, "errors": self.errors, "running": self.running}


jobs: dict[int, Job] = {}
jobs_lock = threading.Lock()


def _run_job(job: Job, project_id: int, image_ids: list[int], profile: TaggingProfile) -> None:
    try:
        _run_job_inner(job, project_id, image_ids, profile)
    except Exception as error:  # noqa: BLE001 - report instead of dying silently in a thread
        job.errors.append({"image_id": None, "message": str(error)})
    finally:
        job.running = False


def _run_job_inner(job: Job, project_id: int, image_ids: list[int], profile: TaggingProfile) -> None:
    with db.session() as conn:
        settings = load_settings(conn)
        trigger = conn.execute("SELECT trigger FROM projects WHERE id = ?", (project_id,)).fetchone()["trigger"]
        rows = {
            r["id"]: r
            for r in conn.execute(
                f"SELECT * FROM images WHERE project_id = ? AND id IN ({','.join('?' * len(image_ids))})",
                (project_id, *image_ids),
            )
        }
    prompt = build_prompt(profile)
    headers = {"Authorization": f"Bearer {settings.tagger_api_key}"} if settings.tagger_api_key else {}
    base_url = settings.tagger_base_url.rstrip("/") + "/"

    def work(image_id: int) -> None:
        if job.cancelled:
            return
        try:
            row = rows[image_id]
            reply = parse_reply(ask_model(client, settings.tagger_model, prompt, encode_image(image_path(row))))
            suggestion = build_suggestion(reply, profile, trigger)
            with db.session() as conn:
                conn.execute(
                    """INSERT INTO tag_suggestions (image_id, caption, groups, issues, model, goal)
                       VALUES (?, ?, ?, ?, ?, ?)
                       ON CONFLICT(image_id) DO UPDATE SET caption = excluded.caption, groups = excluded.groups,
                           issues = excluded.issues, model = excluded.model, goal = excluded.goal""",
                    (
                        image_id,
                        suggestion["caption"],
                        json.dumps(suggestion["groups"]),
                        json.dumps(suggestion["issues"]),
                        settings.tagger_model,
                        profile.goal,
                    ),
                )
        except Exception as error:  # noqa: BLE001 - one failed image must not stop the batch
            job.errors.append({"image_id": image_id, "message": str(error)})
        finally:
            job.done += 1

    with httpx.Client(base_url=base_url, headers=headers, timeout=180) as client:
        with ThreadPoolExecutor(PARALLEL_REQUESTS) as pool:
            list(pool.map(work, [i for i in image_ids if i in rows]))


# --- API ---------------------------------------------------------------------


def _profile(conn: sqlite3.Connection, project_id: int) -> TaggingProfile:
    row = conn.execute("SELECT kind, tagging_profile FROM projects WHERE id = ?", (project_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Project not found")
    if row["tagging_profile"]:
        return TaggingProfile.model_validate_json(row["tagging_profile"])
    return TaggingProfile(goal=row["kind"])


@router.get("/projects/{project_id}/tagging")
def get_tagging(project_id: int, conn: sqlite3.Connection = Depends(db.get_db)):
    profile = _profile(conn, project_id)
    settings = load_settings(conn)
    suggestions = conn.execute(
        """SELECT s.* FROM tag_suggestions s JOIN images i ON i.id = s.image_id
           WHERE i.project_id = ? ORDER BY s.image_id""",
        (project_id,),
    ).fetchall()
    job = jobs.get(project_id)
    return {
        "profile": profile,
        "prompt": build_prompt(profile),
        "configured": bool(settings.tagger_base_url and settings.tagger_model),
        "dictionary_size": len(dictionary()),
        "job": job.snapshot() if job else None,
        "suggestions": [
            {**dict(s), "groups": json.loads(s["groups"]), "issues": json.loads(s["issues"])} for s in suggestions
        ],
    }


@router.post("/tagging/prompt")
def preview_prompt(profile: TaggingProfile):
    return {"prompt": build_prompt(profile)}


class RunTagging(BaseModel):
    image_ids: list[int]
    profile: TaggingProfile


@router.post("/projects/{project_id}/tagging/run")
def run_tagging(project_id: int, body: RunTagging, conn: sqlite3.Connection = Depends(db.get_db)):
    _profile(conn, project_id)  # 404 for an unknown project
    settings = load_settings(conn)
    if not (settings.tagger_base_url and settings.tagger_model):
        raise HTTPException(400, "Set up a vision model first")
    if not body.image_ids:
        raise HTTPException(400, "No images selected")
    conn.execute("UPDATE projects SET tagging_profile = ? WHERE id = ?", (body.profile.model_dump_json(), project_id))
    conn.commit()

    with jobs_lock:
        current = jobs.get(project_id)
        if current and current.running:
            raise HTTPException(409, "Tagging is already running for this project")
        job = jobs[project_id] = Job(len(body.image_ids))
    threading.Thread(
        target=_run_job, args=(job, project_id, body.image_ids, body.profile), name="tagging", daemon=True
    ).start()
    return job.snapshot()


@router.post("/projects/{project_id}/tagging/cancel")
def cancel_tagging(project_id: int):
    job = jobs.get(project_id)
    if job:
        job.cancelled = True
    return {"ok": True}


class Decide(BaseModel):
    image_ids: list[int]
    # Optional edited captions, keyed by image id; otherwise the stored suggestion is used.
    captions: dict[int, str] = {}


@router.post("/tagging/accept")
def accept(body: Decide, conn: sqlite3.Connection = Depends(db.get_db)):
    """Replace each image's caption with its suggestion."""
    updated = []
    for image_id in body.image_ids:
        row = conn.execute("SELECT * FROM tag_suggestions WHERE image_id = ?", (image_id,)).fetchone()
        if row is None:
            continue
        caption = body.captions.get(image_id, row["caption"]).strip()
        if row["groups"] != "{}":  # a tag list, not a sentence: drop repeated tags
            caption = join_tags(split_tags(caption))
        conn.execute(
            "UPDATE images SET caption = ?, caption_source = ? WHERE id = ?",
            (caption, f"{row['model']} ({row['goal']})", image_id),
        )
        conn.execute("DELETE FROM tag_suggestions WHERE image_id = ?", (image_id,))
        updated.append(dict(conn.execute("SELECT * FROM images WHERE id = ?", (image_id,)).fetchone()))
    return updated


@router.post("/tagging/discard")
def discard(body: Decide, conn: sqlite3.Connection = Depends(db.get_db)):
    for image_id in body.image_ids:
        conn.execute("DELETE FROM tag_suggestions WHERE image_id = ?", (image_id,))
    return {"ok": True}
