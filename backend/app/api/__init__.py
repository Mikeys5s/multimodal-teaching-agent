"""HTTP 路由层。

归属按模块切（SPEC §9.1）：
  meta.py / materials.py / extract.py / knowledge.py / graph.py
  report.py / jobs.py                        -> P2
  qa.py                                       -> P3（6 个端点，见下方待办）

统一在这里汇总注册到 app。**新增路由文件后必须在这里 include**，
否则 `app.openapi()` 里看不到它 —— `tests/test_api_contract.py` 会因此失败。

## 待 P3 补齐的端点（api-spec §5，编号 20–25）

```
POST   /api/qa/sessions             创建会话
GET    /api/qa/sessions/{id}        会话详情 + 全部轮次
POST   /api/qa/sessions/{id}/ask    提问（SSE 流式）★
GET    /api/qa/sessions/{id}/state  状态机查询（供前端画引导进度）
GET    /api/qa/sessions/{id}/report 会话诊断报告
DELETE /api/qa/sessions/{id}        删除会话
```

请求/响应模型已在 `app/schemas/qa.py` 备齐（含 `SseRetrievedEvent` / `SseStateEvent` /
`SseDeltaEvent` / `SseDiagnosisEvent` / `SseDoneEvent`），P3 直接引用即可，不用再定义 schema。

⚠️ **SSE 事件必须带 `id: <seq>`**（api-spec v1.3 补充）——`Last-Event-ID` 续推依赖它，
且 `seq` 在一个会话内单调递增、跨轮次不重置。
"""

from fastapi import APIRouter

from app.api import extract, graph, jobs, knowledge, materials, meta, qa, report

api_router = APIRouter(prefix="/api")
api_router.include_router(meta.router)
api_router.include_router(materials.router)
api_router.include_router(extract.router)
api_router.include_router(knowledge.router)
api_router.include_router(graph.router)
api_router.include_router(report.router)
api_router.include_router(jobs.router)
api_router.include_router(qa.router)
