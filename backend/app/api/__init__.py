"""HTTP 路由层。

归属按模块切（SPEC §9.1）：
  meta.py / materials.py / extract.py / knowledge.py / graph.py
  report.py / export.py / jobs.py            -> P2
  qa.py                                       -> P3（本目录只放占位说明，不写实现）

统一在这里汇总注册到 app。**新增路由文件后必须在这里 include**，
否则 `app.openapi()` 里看不到它 —— `tests/test_api_contract.py` 会因此失败。
"""

from fastapi import APIRouter

from app.api import materials, meta

api_router = APIRouter(prefix="/api")
api_router.include_router(meta.router)
api_router.include_router(materials.router)
