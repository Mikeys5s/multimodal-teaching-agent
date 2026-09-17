"""骨架冒烟测试（归属：P2）。

这一步测的不是业务，而是**基础设施有没有搭对**：
响应包封是否统一、request_id 是否注入、错误是否收敛成同一种结构。
这些如果错了，后面 27 个端点会一起错。
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.response import REQUEST_ID_HEADER
from app.main import create_app

client = TestClient(create_app())


def test_health_returns_envelope_and_reports_real_db_state() -> None:
    res = client.get("/api/health")
    assert res.status_code == 200

    body = res.json()
    assert body["ok"] is True
    assert body["request_id"].startswith("req_")

    # db 必须是真实探测结果，不能是写死的占位值
    assert body["data"]["db"] in {"ok"} or body["data"]["db"].startswith("error:")


def test_foreign_keys_pragma_is_actually_enabled() -> None:
    """★ 关键回归测试：SQLite 默认不启用外键，漏设 pragma 会让所有外键形同虚设。

    这条用例的价值在于——将来有人重构 db.py 时，如果不小心去掉了
    event listener，测试会立刻失败，而不是等到数据脏了才发现。
    """
    res = client.get("/api/health/pragma")
    assert res.status_code == 200

    pragmas = res.json()["data"]["pragmas"]
    assert pragmas["foreign_keys"] == "1", "外键约束没生效！检查 db.py 的 connect 事件监听"
    assert pragmas["journal_mode"].lower() == "wal"


def test_capabilities_exposes_limits_for_frontend() -> None:
    res = client.get("/api/meta/capabilities")
    assert res.status_code == 200

    data = res.json()["data"]
    assert ".pdf" in data["supported_material_types"]
    assert data["max_upload_mb"] > 0
    # 音频明确不支持（SPEC §6.1 D-08），不能被误加回来
    assert ".mp3" not in data["supported_material_types"]


def test_request_id_header_present() -> None:
    res = client.get("/api/health")
    assert res.headers.get(REQUEST_ID_HEADER, "").startswith("req_")


def test_unknown_path_returns_error_envelope_not_html() -> None:
    """404 也要走统一包封，前端才不用为错误分支写第二套解析。"""
    res = client.get("/api/definitely-not-exist")
    assert res.status_code == 404

    body = res.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "NOT_FOUND"
    assert body["error"]["message"]


def test_error_message_is_chinese_not_framework_english() -> None:
    """★ 规格硬要求：error.message 必须是能直接展示给用户的中文。

    框架自己抛的 404 会带 detail="Not Found"，如果直接透出去，
    用户就会看到一句英文——这正是 docs/api-spec.md §1.1 要避免的。
    """
    for path in ("/api/definitely-not-exist", "/api/health/nope"):
        body = client.get(path).json()
        message = body["error"]["message"]
        assert message not in {"Not Found", "Method Not Allowed", "Bad Request"}, (
            f"{path} 透出了框架的英文文案：{message}"
        )
        assert any("\u4e00" <= ch <= "\u9fff" for ch in message), (
            f"{path} 的 message 里没有中文字符：{message}"
        )


def test_wrong_method_also_returns_chinese_message() -> None:
    """POST 一个只支持 GET 的端点，也不能吐英文样板。"""
    res = client.post("/api/health")
    assert res.status_code == 405

    body = res.json()
    assert body["ok"] is False
    assert any("\u4e00" <= ch <= "\u9fff" for ch in body["error"]["message"])
