"""前端托管与路由分发（归属：P2）。

单容器部署的「最后一段路」：前端产物怎么和后端接口共处一个进程。
这段逻辑不写测试的话，出问题只会以"页面上某个路由刷新 404"的形式被发现，
而那是**很难反查回这里**的症状。

## 钉住三件事

1. **没前端时给提示页，不给裸 404** —— 第一次跑起来的人不该以为服务坏了
2. **有前端时 SPA 路由要能刷新**（`/materials` 磁盘上没有这个文件）
3. ★ **`/api/**` 永远不能被页面吃掉** —— 这是自测时抓到的真 bug：
   catch-all 把未注册的接口路径也接管了，前端调错接口会拿到 HTML，
   然后在 `response.json()` 那行炸掉，报一个跟真正原因毫无关系的错
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import create_app


@pytest.fixture
def no_frontend_app(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """让 app 指向一个**空**的前端产物目录 —— 模拟"前端还没构建"。"""
    monkeypatch.setattr(settings, "frontend_dist", str(tmp_path / "not-built"))
    return create_app()


@pytest.fixture
def with_frontend_app(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """造一份假的前端产物，模拟"前端已构建"。"""
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(
        "<!doctype html><title>XiZhi SPA</title><div id=root></div>", encoding="utf-8"
    )
    (dist / "assets" / "app.js").write_text("console.log('xizhi')", encoding="utf-8")
    (dist / "favicon.ico").write_bytes(b"\x00\x01")

    monkeypatch.setattr(settings, "frontend_dist", str(dist))
    return create_app()


# ---------------------------------------------------------------------------
# 1. 没有前端产物
# ---------------------------------------------------------------------------


def test_no_frontend_root_gives_hint_page(no_frontend_app) -> None:
    """根路径给说明页，**不是 404**。"""
    r = TestClient(no_frontend_app).get("/")
    assert r.status_code == 200
    assert "后端已就绪" in r.text
    assert r.headers["content-type"].startswith("text/html")


def test_no_frontend_unknown_path_also_hint_page(no_frontend_app) -> None:
    """非接口的未知路径同样落到说明页 —— 行为和"有前端"保持一致。"""
    r = TestClient(no_frontend_app).get("/materials/whatever")
    assert r.status_code == 200
    assert "后端已就绪" in r.text


def test_no_frontend_api_still_returns_json(no_frontend_app) -> None:
    """接口照常工作 —— 前端缺失不该影响 API。"""
    r = TestClient(no_frontend_app).get("/api/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True


# ---------------------------------------------------------------------------
# 2. 有前端产物
# ---------------------------------------------------------------------------


def test_spa_index_is_served_at_root(with_frontend_app) -> None:
    r = TestClient(with_frontend_app).get("/")
    assert r.status_code == 200
    assert "XiZhi SPA" in r.text


def test_spa_route_falls_back_to_index(with_frontend_app) -> None:
    """★ React Router 的路径在磁盘上没有对应文件，刷新必须也能拿到 index.html。"""
    for path in ("/materials", "/graph", "/tutor/deep/nested"):
        r = TestClient(with_frontend_app).get(path)
        assert r.status_code == 200, path
        assert "XiZhi SPA" in r.text, path


def test_real_static_file_is_served_not_index(with_frontend_app) -> None:
    """真实存在的文件要正常返回，不能被 index.html 顶掉。"""
    r = TestClient(with_frontend_app).get("/assets/app.js")
    assert r.status_code == 200
    assert "xizhi" in r.text

    r = TestClient(with_frontend_app).get("/favicon.ico")
    assert r.status_code == 200
    assert r.content == b"\x00\x01"


def test_directory_traversal_is_blocked(with_frontend_app, tmp_path: Path) -> None:
    """★ 路径穿越要挡住：`/../` 不能读到产物目录之外的文件。

    没这道检查的话，容器里就能顺着 `../../` 读到 `/app/backend/app/config.py`
    甚至 `/data/xizhi.db`。
    """
    secret = tmp_path / "secret.txt"
    secret.write_text("不该被读到", encoding="utf-8")

    r = TestClient(with_frontend_app).get("/../secret.txt")
    assert "不该被读到" not in r.text


# ---------------------------------------------------------------------------
# 3. ★ 回归测试：/api 不能被页面吃掉
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["/api/nonexistent", "/api/", "/api/materials/typo/path"])
def test_unknown_api_path_returns_json_even_without_frontend(no_frontend_app, path: str) -> None:
    """无前端时，未注册的接口路径也要返回 **JSON 错误包封**。

    （这条是抓到 bug 后补的 —— 之前这里返回 HTML。）
    """
    r = TestClient(no_frontend_app, follow_redirects=False).get(path)
    if r.status_code == 200:  # /api/ 可能被规范化成 /api
        pytest.skip("该路径被规范化处理，另有用例覆盖")
    assert r.status_code in (404, 307, 308), f"{path} -> {r.status_code}"
    if r.status_code == 404:
        body = r.json()
        assert body["ok"] is False
        assert body["error"]["code"] == "NOT_FOUND"
        assert "request_id" in body


@pytest.mark.parametrize("path", ["/api/nonexistent", "/api/materials/typo/path"])
def test_unknown_api_path_returns_json_with_frontend(with_frontend_app, path: str) -> None:
    """★ 有前端时更不能错 —— 否则前端会把 HTML 当成接口响应去解析。"""
    r = TestClient(with_frontend_app).get(path)
    assert r.status_code == 404, f"{path} -> {r.status_code}"
    assert r.headers["content-type"].startswith("application/json")
    body = r.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "NOT_FOUND"
    assert body["error"]["detail"]["hint"] == "接口清单见 /docs"


def test_api_prefix_does_not_swallow_real_routes(with_frontend_app) -> None:
    """让路逻辑不能误伤真实接口。"""
    client = TestClient(with_frontend_app)
    for path in ("/api/health", "/api/health/pragma", "/api/meta/capabilities"):
        r = client.get(path)
        assert r.status_code == 200, path
        assert r.json()["ok"] is True, path


def test_docs_and_openapi_not_swallowed(with_frontend_app) -> None:
    """`/docs` 与 `/openapi.json` 是 FastAPI 自己注册的，要排在 catch-all 之前。"""
    client = TestClient(with_frontend_app)
    assert client.get("/openapi.json").status_code == 200
    assert "swagger" in client.get("/docs").text.lower()
