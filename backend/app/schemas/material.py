"""素材相关的契约（归属：P2）。对应 docs/api-spec.md §3（端点 4–10）。

**这一层是冻结的对外契约** —— D1 EOD 之后只允许新增字段，不允许改已有字段名或类型。
字段名必须与 `docs/api-spec.md` 逐字一致，`tests/test_api_contract.py` 会做比对。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# 3.1 上传
# ---------------------------------------------------------------------------


class UploadAcceptedOut(BaseModel):
    """被接收的文件 —— 每个文件对应一个独立的解析任务。"""

    material_id: str
    filename: str
    job_id: str


class UploadRejectedOut(BaseModel):
    """被拒绝的文件。`reason` 必须是**能直接展示给用户的中文**。"""

    filename: str = Field(description="原始文件名")
    reason: str = Field(
        description="拒绝原因，人话，如「暂不支持 .pages 格式，请转为 PDF 或 DOCX」"
    )


class UploadResultOut(BaseModel):
    """上传结果。

    ⚠️ 契约要点：**部分文件被拒绝时仍返回 202**，`rejected` 数组给出可读原因，
    **不得整批失败** —— 一次传 5 个文件、其中 1 个格式不对，不该让另外 4 个也白传。
    """

    accepted: list[UploadAcceptedOut] = Field(default_factory=list)
    rejected: list[UploadRejectedOut] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 3.2 清单与详情
# ---------------------------------------------------------------------------


class UncertainNoteOut(BaseModel):
    """存疑处（`materials.uncertain_notes` 的元素，data-model §3.1）。

    "宁缺毋错"原则的对外体现：解析拿不准的地方**主动标出来**，不装完美。
    """

    kind: str = Field(
        description="low_confidence_ocr / missing_field / ambiguous_structure / other"
    )
    page: int | None = Field(default=None, description="所在页码")
    block_id: str | None = Field(default=None, description="定位到具体解析块")
    message: str = Field(description="给用户看的中文说明")
    severity: str = Field(description="high / medium / low")


class MaterialItemOut(BaseModel):
    """素材清单项，也被「素材详情」复用（api-spec §3.3 注明「同 3.2 结构」）。"""

    id: str
    filename: str
    mime_type: str
    size_bytes: int
    source_type: str = Field(description="pdf_text / pdf_scan / docx / pptx / image / audio")
    parse_method: str | None = Field(
        default=None, description="实际使用的解析方式：text_extract / multimodal_llm / ocr / asr"
    )
    status: str = Field(description="pending / parsing / done / failed / partial")

    page_count: int | None = None
    duration_sec: int | None = Field(
        default=None, description="音频时长。字段保留，初赛不启用（SPEC §6.1 D-08）"
    )
    char_count: int | None = None
    quality_score: float | None = Field(default=None, description="解析质量自评 0–1")

    uncertain_count: int = Field(default=0, description="存疑处条数，便于列表页直接显示角标")
    uncertain_notes: list[UncertainNoteOut] = Field(default_factory=list)

    created_at: str


# ---------------------------------------------------------------------------
# 3.3 解析块与大纲
# ---------------------------------------------------------------------------


class BlockOut(BaseModel):
    """解析块 —— Markdown 预览与高亮定位的数据源。"""

    id: str
    seq: int
    page_no: int | None = None
    line_start: int | None = None
    line_end: int | None = None
    block_type: str
    heading_level: int | None = None
    content_md: str
    image_path: str | None = None
    ocr_confidence: float | None = None


class OutlineSectionOut(BaseModel):
    """大纲中的一节。`knowledge_point_count` 让前端能显示"这一节抽了几个知识点"。"""

    id: str
    number: str | None = None
    title: str
    seq: int
    knowledge_point_count: int = 0


class OutlineChapterOut(BaseModel):
    id: str
    number: str | None = None
    title: str
    seq: int
    sections: list[OutlineSectionOut] = Field(default_factory=list)


class OutlineOut(BaseModel):
    """章 → 节的骨架。**未抽知识点时的中间态**，也是校验三级结构完整率的对象。"""

    material_id: str
    chapters: list[OutlineChapterOut] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 3.3 从素材抽出的题目
# ---------------------------------------------------------------------------


class QuestionOut(BaseModel):
    """`questions` 表的对外表示（从材料抽出的**原始**题目）。

    与 `kp_examples` 的区别：这里可能还没归属到知识点，且**可能没有答案**
    （`answer_missing=true` 对应 Stage 1 的"存疑处"）。
    """

    id: str
    material_id: str
    source_page: int | None = None
    source_block_id: str | None = None
    question_type: str
    stem_md: str
    options_json: str | None = Field(default=None, description="选项数组 JSON 字符串")
    answer_md: str | None = Field(default=None, description="材料未给答案时为 null")
    answer_missing: bool = Field(description="材料里就没有答案 —— 与存疑处一一对应")
    extraction_confidence: float | None = None
    pk_kp_id: str | None = Field(default=None, description="归属知识点，Stage 2 回填")


# ---------------------------------------------------------------------------
# 3.4 重试
# ---------------------------------------------------------------------------


class ReparseAcceptedOut(BaseModel):
    """`POST /api/materials/{id}/reparse` 的响应（202）。

    失败隔离：某份素材解析失败可以单独重试，不影响其他素材。
    """

    material_id: str
    job_id: str
