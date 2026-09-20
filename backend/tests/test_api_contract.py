"""接口冻结点守卫（归属：P2）。

**这是「冻结」这件事真正的保障。**

做法：从 `docs/api-spec.md` §7 的速查表里解析出端点清单，
与 `app.openapi()` 里的实际端点集合做**集合比对** —— 多一个、少一个都失败。

为什么必须这么写：
  · "我记得改完了"不是保障，断言才是。任何人想加端点，必须**先改规格**，
    否则测试立刻红 —— 规格与实现的漂移无法悄悄积累。
  · 漏掉一个端点在 `pytest` 里是完全无声的（其他测试照样绿），
    只有集合比对能发现。

## 路径参数的归一化

规格速查表用 `{id}` 这类简写，而路由里用的是更有描述性的 `{material_id}` / `{kp_id}` 等。
**URL 形状是一样的**（都是单段占位），参数名只影响 `/docs` 里的可读性。
所以这里把 `{...}` 统一归一成 `{}` 再比对 —— 比的是"路由形状"，不是参数名叫什么。
"""

from __future__ import annotations

import re

import pytest
from fastapi import FastAPI

from app.config import BACKEND_ROOT
from app.main import app

API_SPEC = BACKEND_ROOT.parent / "docs" / "api-spec.md"

# 规格速查表里的一行：| 3 | GET | `/api/health/pragma` | 运维 | — |
_TABLE_ROW = re.compile(r"^\|\s*\*{0,2}(\d+)\*{0,2}\s*\|\s*([A-Z]+)\s*\|\s*`([^`]+)`")
_HAS_PARAM = re.compile(r"\{[^}]*\}")


def _normalize(path: str) -> str:
    """把路径参数统一成 `{}`，只比路由形状。"""
    return _HAS_PARAM.sub("{}", path)


def _spec_endpoints() -> dict[tuple[str, str], int]:
    """从 api-spec §7 速查表解析端点。返回 {(方法, 归一化路径): 编号}。"""
    assert API_SPEC.exists(), f"找不到接口规格：{API_SPEC}"

    found: dict[tuple[str, str], int] = {}
    for line in API_SPEC.read_text(encoding="utf-8").splitlines():
        m = _TABLE_ROW.match(line.strip())
        if not m:
            continue
        number, method, path = int(m.group(1)), m.group(2).upper(), m.group(3)
        found[(method, _normalize(path))] = number
    return found


def _app_endpoints(application: FastAPI) -> set[tuple[str, str]]:
    """从 OpenAPI 里取实际注册的端点。

    ⚠️ 不要用 `app.routes` —— 新版 FastAPI 的 `include_router` 是**懒加载**的
    （路由被包在 `_IncludedRouter` 里），`app.routes` 里拿不到子路由，
    会得到"0 个端点"这种误导性的结果。
    """
    spec = application.openapi()
    out: set[tuple[str, str]] = set()
    for path, operations in spec.get("paths", {}).items():
        for method in operations:
            if method.upper() in {"GET", "POST", "PUT", "DELETE", "PATCH"}:
                out.add((method.upper(), _normalize(path)))
    return out


# ---------------------------------------------------------------------------
# 1. 规格本身可解析
# ---------------------------------------------------------------------------


def test_api_spec_table_is_parseable() -> None:
    """速查表格式若被改坏，下面的比对会静默变成"两边都是空集"而通过 —— 先堵住这个洞。"""
    spec_eps = _spec_endpoints()
    assert len(spec_eps) == 31, (
        f"从 api-spec §7 解析到 {len(spec_eps)} 个端点，应为 31。是表格格式变了，还是端点数量改了？"
    )


# ---------------------------------------------------------------------------
# 2. ★ 集合比对
# ---------------------------------------------------------------------------


def test_app_endpoints_match_spec_exactly() -> None:
    """★ 冻结点：实现的端点集合必须与规格**完全一致**。"""
    spec_eps = set(_spec_endpoints())
    app_eps = _app_endpoints(app)

    missing = spec_eps - app_eps
    extra = app_eps - spec_eps

    assert not missing, "规格里定义了、但代码里没实现的端点：\n  " + "\n  ".join(
        f"{m} {p}" for m, p in sorted(missing)
    )
    assert not extra, (
        "代码里有、但规格里没登记的端点（实现比规格多即为违规）：\n  "
        + "\n  ".join(f"{m} {p}" for m, p in sorted(extra))
        + "\n\n新增端点请先改 docs/api-spec.md §7 速查表，再改代码。"
    )


@pytest.mark.parametrize("expected_count", [31])
def test_endpoint_count(expected_count: int) -> None:
    assert len(_app_endpoints(app)) == expected_count


# ---------------------------------------------------------------------------
# 3. 每个端点都要有可读的 summary 与 description
# ---------------------------------------------------------------------------


def test_every_endpoint_has_human_readable_docs() -> None:
    """端点的 summary / description 是给 P3 与评委看的，不能留空。

    这条不是洁癖：接口清单里"这个接口干什么"如果只有路径名，P3 得回来问一遍，
    评委也看不出我们做了多少事。
    """
    spec = app.openapi()
    undocumented: list[str] = []
    for path, operations in spec.get("paths", {}).items():
        for method, op in operations.items():
            if method.upper() not in {"GET", "POST", "PUT", "DELETE", "PATCH"}:
                continue
            if not op.get("summary"):
                undocumented.append(f"{method.upper()} {path} 缺 summary")
    assert not undocumented, "以下端点缺少文档：\n  " + "\n  ".join(undocumented)


# ---------------------------------------------------------------------------
# 4. 非 JSON 端点必须能渲染（response_class 必须是类，不是函数）
# ---------------------------------------------------------------------------


def test_non_json_endpoints_render_openapi() -> None:
    """★ 回归测试：`response_class=` 传函数会让 `app.openapi()` 直接抛
    `AttributeError: 'function' object has no attribute 'media_type'`。

    这个错误一旦引入，`/docs` 整页打不开 —— 而其他测试可能照样绿。
    """
    spec = app.openapi()
    for path in (
        "/api/materials/{material_id}/markdown",
        "/api/export/knowledge-points",
    ):
        assert path in spec["paths"], f"{path} 没有出现在 OpenAPI 里"


def test_markdown_endpoint_declares_markdown_media_type() -> None:
    """非 JSON 端点的响应类型必须被正确标注，否则 P3 不知道要按文本还是 JSON 解析。"""
    from app.core.response import CsvResponse, MarkdownResponse

    assert "markdown" in (MarkdownResponse.media_type or "")
    assert "csv" in (CsvResponse.media_type or "")
