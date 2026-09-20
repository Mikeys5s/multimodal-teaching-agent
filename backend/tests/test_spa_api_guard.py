"""`/api/**` 落到 catch-all 时必须返回 **JSON 404**，不能返回页面。

## 为什么要有这条测试

catch-all 是 `/{full_path:path}`，非常贪婪 —— 它会连带把**未注册的接口路径**也吃掉。
后果不是"少了个 404"，而是**前端调错接口时拿到 HTML**，
然后在 `response.json()` 那一行炸掉，报一个跟真正原因毫无关系的错。
我们的错误包封约定（`{ok:false, error:{...}}`）也就此被绕过。

P3 在 #66 §7 报过一个现象：某个 30 秒窗口里 `/api/materials` 等返回了 SPA HTML 且状态码 200。
**代码里其实已经有防护**（`main._reject_unknown_api_path`），
而且那个窗口对得上一次容器重建（不是代码缺陷）。
但"有防护"和"有断言证明防护生效"是两件事 —— **这条测试把后者补上**。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.mark.parametrize(
    "path",
    [
        "/api/definitely-not-registered",
        "/api/materials/xxx/nonexistent-sub",
        "/api/learnng-path",      # 拼错的真实端点：最常见的一类
    ],
)
def test_unknown_api_path_returns_json_not_html(client: TestClient, path: str) -> None:
    r = client.get(path)

    # ★ 不能是 200 + HTML —— 那正是 P3 观察到的坏窗口
    ctype = r.headers.get("content-type", "")
    assert "text/html" not in ctype, (
        f"{path} 返回了 HTML（content-type={ctype}）—— "
        "catch-all 把接口路径吃掉了，前端会在 response.json() 上炸"
    )
    assert r.status_code == 404, f"{path} 期望 404，实际 {r.status_code}"

    # ★ 必须是我们的错误包封，而不是 FastAPI 裸 404
    body = r.json()
    assert body.get("ok") is False, f"{path} 没有走错误包封：{body}"
    assert body["error"]["code"] == "NOT_FOUND"


def test_spa_still_serves_page_routes(client: TestClient) -> None:
    """页面路由（非 /api）该回落 index.html —— 别把 SPA 回退一起修坏了。"""
    r = client.get("/graph")
    # 没有前端产物时会给一句人话的 HTML；有产物时是 index.html。
    # **两者都不是 JSON 错误** —— 这条断言的就是这个。
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")
