from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from edgeforge.api.app import create_app


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<app-root></app-root>")
    (web / "main.js").write_text("console.log('app')")
    (tmp_path / "secret.txt").write_text("outside")
    # No endpoint below touches the database.
    return TestClient(create_app(sessionmaker[Session](), web_dir=web))


def test_serves_built_files(client: TestClient) -> None:
    response = client.get("/main.js")
    assert response.status_code == 200
    assert response.text == "console.log('app')"


@pytest.mark.parametrize("path", ["/", "/EPL", "/EPL/compare?home=a&away=b"])
def test_client_routes_get_index_html(client: TestClient, path: str) -> None:
    response = client.get(path)
    assert response.status_code == 200
    assert "<app-root>" in response.text


@pytest.mark.parametrize("path", ["/../secret.txt", "/%2E%2E/secret.txt", "/..%2Fsecret.txt"])
def test_files_outside_the_build_are_never_served(client: TestClient, path: str) -> None:
    assert "outside" not in client.get(path).text


def test_unknown_api_paths_are_not_swallowed(client: TestClient) -> None:
    assert client.get("/api/nope").status_code == 404


def test_without_a_build_only_the_api_is_served(tmp_path: Path) -> None:
    client = TestClient(create_app(sessionmaker[Session](), web_dir=tmp_path))
    assert client.get("/").status_code == 404
    assert client.get("/api/docs").status_code == 200
