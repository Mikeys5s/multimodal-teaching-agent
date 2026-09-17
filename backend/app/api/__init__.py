"""HTTP 路由层。

归属按模块切（SPEC §9.1）：
  materials.py / knowledge.py / meta.py  -> P2
  qa.py                                   -> P3
统一在这里汇总注册到 app。
"""

from fastapi import APIRouter

from app.api import meta

api_router = APIRouter(prefix="/api")
api_router.include_router(meta.router)
