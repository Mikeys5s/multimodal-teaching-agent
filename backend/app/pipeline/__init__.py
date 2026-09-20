"""解析与抽取的**任务层**（归属：P2）。

## 这个包为什么叫 pipeline

因为它装的是**「把零件接起来」的那一层**，不是零件本身。

本项目曾经有过这么一段：`app/parse`（P1 的解析链，完整且测试齐全）、
`app/extract`（抽取）、`skills/xizhi-graph-infer`（依赖图算法，完整且实测过）
—— **每个零件都做好了，而它们之间没有连线**：
**没有任何 API 文件 import 过 `app.parse`**，上传端点也只做校验不落库。

所以端到端从未跑通，而"看起来一切都好"：28 个端点、400+ 测试全绿、六个页面、部署上线。

**这个包就是那些连线。** 里面每个模块的职责都是：
**触发一个真实任务 → 调用已有的零件 → 把结果落到该落的表 → 正确维护状态与事务边界。**
"""

from __future__ import annotations

from app.pipeline.extract_knowledge import run_extract, run_extract_job
from app.pipeline.parse_material import (
    clear_derived,
    persist_outline,
    run_parse,
    run_parse_job,
)

__all__ = [
    "clear_derived",
    "persist_outline",
    "run_extract",
    "run_extract_job",
    "run_parse",
    "run_parse_job",
]
