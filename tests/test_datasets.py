import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("LORACRAFT_HOME", str(tmp_path))
    from loracraft.server.app import app

    with TestClient(app, base_url="http://127.0.0.1") as c:
        yield c


def png(color, size=(64, 96)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


def test_project_and_image_flow(client):
    project = client.post("/api/projects", json={"name": "Test", "trigger": "tst"}).json()
    pid = project["id"]

    files = [
        ("files", ("a.png", png("red"), "image/png")),
        ("files", ("a.txt", b"1girl,  smile , 1girl", "text/plain")),
        ("files", ("b.png", png("blue"), "image/png")),
    ]
    result = client.post(f"/api/projects/{pid}/images", files=files).json()
    assert len(result["added"]) == 2
    a, b = result["added"]
    assert a["caption"] == "1girl, smile"  # trimmed and de-duplicated
    assert (a["width"], a["height"]) == (64, 96)

    # The same file again is skipped as a duplicate.
    again = client.post(f"/api/projects/{pid}/images", files=[("files", ("c.png", png("red"), "image/png"))]).json()
    assert again == {"added": [], "skipped_duplicates": 1, "unreadable": []}

    edited = client.post(
        "/api/tags/edit",
        json={
            "image_ids": [a["id"], b["id"]],
            "add": ["tst"],
            "add_position": "start",
            "remove": ["smile"],
            "replace": {"1girl": "solo"},
        },
    ).json()
    assert [e["caption"] for e in edited] == ["tst, solo", "tst"]

    assert client.get(f"/api/images/{a['id']}/thumb").headers["content-type"] == "image/webp"

    client.post("/api/images/delete", json={"image_ids": [a["id"]]})
    assert len(client.get(f"/api/projects/{pid}/images").json()) == 1
    assert client.get("/api/projects").json()[0]["image_count"] == 1


def test_unreadable_file_does_not_abort_an_import(client):
    pid = client.post("/api/projects", json={"name": "Test"}).json()["id"]
    files = [
        ("files", ("a.png", png("red"), "image/png")),
        ("files", ("broken.png", b"not an image", "image/png")),
        ("files", ("c.png", png("green"), "image/png")),
    ]
    result = client.post(f"/api/projects/{pid}/images", files=files).json()
    assert [i["filename"] for i in result["added"]] == ["a.png", "c.png"]
    assert result["unreadable"] == ["broken.png"]
    assert len(client.get(f"/api/projects/{pid}/images").json()) == 2


def test_delete_tolerates_ids_that_are_already_gone(client):
    pid = client.post("/api/projects", json={"name": "Test"}).json()["id"]
    added = client.post(f"/api/projects/{pid}/images", files=[("files", ("a.png", png("red"), "image/png"))]).json()
    image_id = added["added"][0]["id"]
    assert client.post("/api/images/delete", json={"image_ids": [image_id, 9999]}).status_code == 200
    assert client.get(f"/api/projects/{pid}/images").json() == []

    # Ids are never handed out twice: URLs and cached thumbnails are keyed on them.
    again = client.post(f"/api/projects/{pid}/images", files=[("files", ("b.png", png("blue"), "image/png"))]).json()
    assert again["added"][0]["id"] > image_id


def test_dataset_is_locked_while_a_training_is_queued(client, tmp_path):
    from loracraft.server import db

    pid = client.post("/api/projects", json={"name": "Test"}).json()["id"]
    added = client.post(f"/api/projects/{pid}/images", files=[("files", ("a.png", png("red"), "image/png"))]).json()
    with db.connect() as conn:
        conn.execute("INSERT INTO runs (project_id, name, status, config) VALUES (?, 'r', 'done', '{}')", (pid,))
        conn.execute("UPDATE runs SET status = 'running'")
    assert client.post("/api/images/delete", json={"image_ids": [added["added"][0]["id"]]}).status_code == 409
    assert client.delete(f"/api/projects/{pid}").status_code == 409


def test_static_route_cannot_leave_the_web_directory(client, tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("top secret")
    for path in (f"/{secret.as_posix()}", "/..%2F..%2Fpyproject.toml", "/%2E%2E/%2E%2E/pyproject.toml"):
        response = client.get(path)
        assert "top secret" not in response.text
        assert "[project]" not in response.text


def test_transparent_images_are_flattened_onto_white():
    from loracraft.imaging import to_rgb

    assert to_rgb(Image.new("RGBA", (2, 2), (0, 0, 0, 0))).getpixel((0, 0)) == (255, 255, 255)
    assert to_rgb(Image.new("RGB", (2, 2), "red")).getpixel((0, 0)) == (255, 0, 0)
