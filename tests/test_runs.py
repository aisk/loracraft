import json
import struct

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from loracraft.server import db, runs, system


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("LORACRAFT_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(runs.queue, "start", lambda: None)  # no trainer processes in tests
    monkeypatch.setattr(system, "trainer_status", lambda: {"ready": True})  # nor a GPU
    from loracraft.server.app import app

    with TestClient(app, base_url="http://127.0.0.1") as c:
        yield c


@pytest.fixture
def run(client, tmp_path):
    """A queued run of a one-image project."""
    base_model = tmp_path / "model.safetensors"
    base_model.write_bytes(b"")
    image = tmp_path / "a.png"
    Image.new("RGB", (64, 64), "red").save(image)

    pid = client.post("/api/projects", json={"name": "Test"}).json()["id"]
    with open(image, "rb") as f:
        client.post(f"/api/projects/{pid}/images", files=[("files", ("a.png", f, "image/png"))])
    response = client.post(f"/api/projects/{pid}/runs", json={"config": {"base_model": str(base_model)}})
    assert response.status_code == 200
    return response.json()


def row_of(run_id: int):
    with db.session() as conn:
        return conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()


def write_events(run_id: int, *events: dict, tail: str = "") -> None:
    with open(runs.run_dir(row_of(run_id)) / "events.jsonl", "a", encoding="utf-8") as f:
        f.writelines(json.dumps(e) + "\n" for e in events)
        f.write(tail)


def step(n: int) -> dict:
    return {"type": "step", "step": n, "epoch": 1, "loss_avg": 0.1, "seconds": float(n)}


def test_progress_follows_the_event_log_as_it_grows(client, run):
    write_events(run["id"], {"type": "start", "total_steps": 10, "steps_per_epoch": 5}, step(1), tail='{"type": "st')
    progress = client.get(f"/api/runs/{run['id']}").json()["progress"]
    assert (progress["step"], progress["total_steps"], progress["seconds_per_step"]) == (1, 10, 1.0)

    # The half-written line is completed and more follow; nothing is counted twice or lost.
    write_events(run["id"], tail='ep", "step": 2, "epoch": 1, "loss_avg": 0.1, "seconds": 2.0}\n')
    write_events(run["id"], step(3))
    progress = client.get(f"/api/runs/{run['id']}").json()["progress"]
    assert (progress["step"], progress["seconds_per_step"]) == (3, 2.0)

    events = client.get(f"/api/runs/{run['id']}/events", params={"after": 2}).json()["events"]
    assert [e["step"] for e in events] == [2, 3]


@pytest.mark.parametrize(
    ("events", "exit_code", "status"),
    [
        ([{"type": "done", "stopped": False}], 0, "done"),
        ([{"type": "done", "stopped": True}], 0, "stopped"),
        ([{"type": "done", "stopped": False}], 1, "failed"),
        ([], 0, "failed"),  # exited without saying it was done
        ([{"type": "done", "stopped": False}], None, "done"),  # a trainer adopted from a previous server
    ],
)
def test_finalize_judges_a_run_by_its_event_log(client, run, events, exit_code, status):
    write_events(run["id"], *events)
    runs.queue._finalize(row_of(run["id"]), exit_code)
    assert row_of(run["id"])["status"] == status


def test_a_run_stopped_while_queued_is_not_started(client, run, monkeypatch):
    picked = row_of(run["id"])  # the queue has read the row...
    client.post(f"/api/runs/{run['id']}/stop")  # ...and the user stops it before the trainer starts
    monkeypatch.setattr(runs.subprocess, "Popen", lambda *a, **k: pytest.fail("trainer was started"))
    runs.queue._execute(picked)
    assert row_of(run["id"])["status"] == "stopped"


def test_delete_run_removes_its_files_but_not_while_active(client, run):
    directory = runs.run_dir(row_of(run["id"]))
    assert client.delete(f"/api/runs/{run['id']}").status_code == 409  # still queued

    client.post(f"/api/runs/{run['id']}/stop")
    assert client.delete(f"/api/runs/{run['id']}").status_code == 200
    assert not directory.exists()
    assert client.get(f"/api/projects/{run['project_id']}/runs").json() == []


def test_impossible_settings_are_refused_when_the_run_is_created(client, run):
    config = {"base_model": run["config"]["base_model"], "batch_size": 0}
    assert client.post(f"/api/projects/{run['project_id']}/runs", json={"config": config}).status_code == 422


def test_damaged_checkpoint_is_not_listed_and_does_not_break_the_list(client, tmp_path):
    (tmp_path / "damaged.safetensors").write_bytes(struct.pack("<Q", 2**62) + b"x" * 100)
    assert system.inspect_checkpoint(tmp_path / "damaged.safetensors")["is_sdxl"] is False


def test_only_local_pages_may_use_the_api(client):
    assert client.get("/api/projects", headers={"Host": "evil.example"}).status_code == 403
    assert client.get("/api/projects", headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.get("/api/projects", headers={"Origin": "http://localhost:5600"}).status_code == 200
