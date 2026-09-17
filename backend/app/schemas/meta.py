"""元信息相关的响应模型（归属：P2）。对应 docs/api-spec.md §2。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class HealthOut(BaseModel):
    """`GET /api/health` 的响应体（docs/api-spec.md §2）。"""

    status: str = Field(description="服务整体状态：ok / degraded / down")
    db: str = Field(description="数据库状态：ok / error:xxx")
    llm: str = Field(description="模型通道状态；当前架构为 not_in_use（离线构建 + 在线零模型依赖）")
    version: str = Field(description="后端版本号")


class DbPragmaOut(BaseModel):
    """SQLite pragma 实际值，用于自检「设置真的生效了」。"""

    journal_mode: str
    foreign_keys: str = Field(description="必须为 1；为 0 说明外键约束没生效")
    busy_timeout: str


class HealthPragmaOut(BaseModel):
    """`GET /api/health/pragma` 的响应体（v1.3 补登记）。"""

    pragmas: DbPragmaOut
    db_file: str = Field(description="当前实际使用的数据库文件绝对路径")


class CapabilitiesOut(BaseModel):
    """`GET /api/meta/capabilities` 的响应体。

    前端据此渲染上传提示，**避免把「支持 PDF、不超过 50MB」这类信息硬编码在前端**。
    """

    supported_material_types: list[str] = Field(description="支持的素材扩展名，如 .pdf / .docx")
    max_upload_mb: int
    parse_methods: dict[str, str] = Field(
        default_factory=dict, description="每种扩展名走哪条解析路径（给用户看的说明文案）"
    )
    llm_mode: str = Field(
        default="not_in_use",
        description="模型通道模式。当前为 not_in_use —— 离线构建 + 在线零模型依赖（SPEC §4.8）",
    )
