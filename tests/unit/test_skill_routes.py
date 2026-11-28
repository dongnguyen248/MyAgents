from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from asf.api.skill_routes import MAX_FILE_BYTES, skill_router


def client_for(root: Path) -> TestClient:
    app = FastAPI()
    app.include_router(skill_router(root))
    return TestClient(app)


def make_skill(root: Path, name: str, text: str) -> Path:
    directory = root / name
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text(text, encoding="utf-8")
    return directory


def test_catalogue_loads_every_skill_and_nested_files(tmp_path: Path) -> None:
    python = make_skill(
        tmp_path,
        "python",
        "---\nname: Python\ndescription: >-\n  Useful skill\ndigest: Short\n---\nBody",
    )
    nested = python / "scripts"
    nested.mkdir()
    (nested / "run.py").write_text("hello", encoding="utf-8")
    (python / "empty").mkdir()
    make_skill(tmp_path, "custom", "---\nbroken: [\n---\n")
    (tmp_path / "not-a-skill").mkdir()
    client = client_for(tmp_path)
    skills = client.get("/skills").json()
    assert [skill["id"] for skill in skills] == ["custom", "python"]
    assert skills[0]["appliesTo"] == []
    assert skills[1]["description"] == "Useful skill"
    assert skills[1]["files"] == ["SKILL.md", "empty/", "scripts/", "scripts/run.py"]
    assert "implement" in skills[1]["appliesTo"]
    assert skills[1]["stackOnly"] is True


def test_read_edit_and_reload_file(tmp_path: Path) -> None:
    make_skill(tmp_path, "custom", "---\nname: custom\ndescription: Before\n---\nBody")
    client = client_for(tmp_path)
    url = "/skills/custom/files/SKILL.md"
    assert "Before" in client.get(url).json()["content"]
    text = "---\nname: custom\ndescription: After\n---\nNew body"
    assert client.put(url, json={"content": text}).status_code == 200
    assert client.get(url).json()["content"] == text
    assert client.get("/skills").json()[0]["description"] == "After"
    assert client.put("/skills/custom/files/new.txt", json={"content": "x"}).status_code == 404


def test_rejects_traversal_symlinks_binary_and_large_files(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    directory = make_skill(root, "custom", "hello")
    secret = tmp_path / "secret"
    secret.write_text("secret", encoding="utf-8")
    (directory / "link").symlink_to(secret)
    (directory / "outside").symlink_to(tmp_path, target_is_directory=True)
    (root / "linked").symlink_to(directory, target_is_directory=True)
    (directory / "binary").write_bytes(b"\xff")
    (directory / "large").write_bytes(b"x" * (MAX_FILE_BYTES + 1))
    client = client_for(root)
    files = client.get("/skills").json()[0]["files"]
    assert "link" not in files
    assert len(client.get("/skills").json()) == 1
    for path in ["link", "outside/secret", "%2e%2e/secret"]:
        assert client.get(f"/skills/custom/files/{path}").status_code in (400, 404)
        assert client.put(f"/skills/custom/files/{path}", json={"content": "bad"}).status_code in (
            400,
            404,
        )
    assert client.get("/skills/linked/files/SKILL.md").status_code == 404
    assert client.get("/skills/custom/files/binary").status_code == 400
    assert client.get("/skills/custom/files/large").status_code == 413
    assert (
        client.put(
            "/skills/custom/files/SKILL.md", json={"content": "x" * (MAX_FILE_BYTES + 1)}
        ).status_code
        == 413
    )
    assert secret.read_text(encoding="utf-8") == "secret"
