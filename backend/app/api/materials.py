"""素材相关路由（归属：P2）。对应 docs/api-spec.md §3，端点 4–12。

## 骨架阶段的实现口径（团队约定 D-22）

**输入校验按规格真实实现，业务数据返回 mock。**

理由：接口冻结的价值主要在**错误分支**上 —— 正常路径 P3 一眼能看懂，
但"参数越界返回什么""文件格式不对返回什么"才是前后端最容易对不齐的地方。
而这些校验逻辑（格式白名单、大小上限）本来就和业务无关，现在写和以后写成本一样。

所以本文件里：
  · **真实**：扩展名白名单、文件大小上限、分页参数、job 冲突检测、404
  · **mock**：素材内容本身（清单、解析块、大纲、题目）

`MOCK_MODE` 是唯一的开关 —— D6 实现真实业务时把它置为 False 即可，
路由签名与响应结构不用动。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.errors import ApiError, ErrorCode
from app.core.pagination import PageData, PageParams
from app.core.response import Envelope, MarkdownResponse, ok, text_response
from app.db import get_db
from app.models import Job, Material
from app.models.ids import block_id, hash_bytes
from app.models.ids import material_id as make_material_id
from app.schemas.material import (
    BlockOut,
    MaterialItemOut,
    OutlineChapterOut,
    OutlineOut,
    OutlineSectionOut,
    QuestionOut,
    ReparseAcceptedOut,
    UncertainNoteOut,
    UploadAcceptedOut,
    UploadRejectedOut,
    UploadResultOut,
)

router = APIRouter(tags=["materials"])

DbSession = Annotated[Session, Depends(get_db)]
PageDep = Annotated[PageParams, Depends(PageParams.as_dependency)]

# ★ 骨架阶段开关：True = 业务数据返回 mock；D6 实现真实业务时置 False
MOCK_MODE = True

SUPPORTED_EXTENSIONS = (".pdf", ".docx", ".pptx", ".jpg", ".jpeg", ".png")
MATERIAL_STATUSES = ("pending", "parsing", "done", "failed", "partial")
BLOCK_TYPES = (
    "heading",
    "paragraph",
    "table",
    "code",
    "formula",
    "image_caption",
    "question",
    "other",
)


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------


def _ext_of(filename: str) -> str:
    idx = filename.rfind(".")
    return filename[idx:].lower() if idx >= 0 else ""


def _require_material(material_id: str, db: Session) -> Material | None:
    """校验素材存在性。

    mock 模式：格式合法即视为存在（不查库），这样 P3 立刻能看到完整响应体；
    D6 之后：真实查库，查不到就 404。
    """
    if not material_id.startswith("mat_"):
        raise ApiError(ErrorCode.NOT_FOUND, f"素材 {material_id} 不存在（id 应以 mat_ 开头）")
    if MOCK_MODE:
        return None
    mat = db.get(Material, material_id)
    if mat is None:
        raise ApiError(ErrorCode.NOT_FOUND, f"素材 {material_id} 不存在")
    return mat


def _parse_block_type(block_type: str | None) -> str | None:
    if block_type is None:
        return None
    if block_type not in BLOCK_TYPES:
        raise ApiError(
            ErrorCode.INVALID_PARAM,
            f"block_type 取值不合法：{block_type}",
            {"allowed": list(BLOCK_TYPES)},
        )
    return block_type


def _mock_material(material_id: str = "mat_9f2a1c40") -> MaterialItemOut:
    """一份像样的样例素材 —— 用目标学科（计算机网络）的内容，演示时也直接用得上。"""
    return MaterialItemOut(
        id=material_id,
        filename="第5章-传输层.pdf",
        mime_type="application/pdf",
        size_bytes=2481920,
        source_type="pdf_scan",
        parse_method="multimodal_llm",
        status="partial",
        page_count=20,
        duration_sec=None,
        char_count=18422,
        quality_score=0.86,
        uncertain_count=2,
        uncertain_notes=[
            UncertainNoteOut(
                kind="low_confidence_ocr",
                page=7,
                block_id=block_id(material_id, 42),
                message="第 7 页手写批注识别置信度 0.62，可能是『窗口单位是字节』",
                severity="medium",
            ),
            UncertainNoteOut(
                kind="missing_field",
                page=12,
                block_id=None,
                message="第 12 页第 3 题只有题干与选项，未找到答案",
                severity="high",
            ),
        ],
        created_at="2026-09-17T13:02:11+00:00",
    )


def _mock_blocks(material_id: str) -> list[BlockOut]:
    samples = [
        ("heading", 1, "5.3 TCP 拥塞控制"),
        ("paragraph", None, "拥塞窗口 cwnd 的大小由发送方根据网络拥塞程度动态调整。"),
        ("formula", None, "$$cwnd = cwnd + MSS \\times \\frac{MSS}{cwnd}$$"),
        ("table", None, "| 阶段 | 行为 |\n|---|---|\n| 慢启动 | cwnd 指数增长 |"),
    ]
    out: list[BlockOut] = []
    for seq, (btype, level, content) in enumerate(samples):
        out.append(
            BlockOut(
                id=block_id(material_id, seq),
                seq=seq,
                page_no=88 + seq // 2,
                line_start=seq * 3 + 1,
                line_end=seq * 3 + 3,
                block_type=btype,
                heading_level=level,
                content_md=content,
                image_path=None,
                ocr_confidence=0.94 if btype == "paragraph" else None,
            )
        )
    return out


def _mock_outline(material_id: str) -> OutlineOut:
    return OutlineOut(
        material_id=material_id,
        chapters=[
            OutlineChapterOut(
                id="ch_9f2a1c40_000",
                number="5",
                title="传输层",
                seq=0,
                sections=[
                    OutlineSectionOut(
                        id="sec_9f2a1c40_000_000",
                        number="5.1",
                        title="传输层概述",
                        seq=0,
                        knowledge_point_count=4,
                    ),
                    OutlineSectionOut(
                        id="sec_9f2a1c40_000_001",
                        number="5.2",
                        title="可靠数据传输",
                        seq=1,
                        knowledge_point_count=7,
                    ),
                    OutlineSectionOut(
                        id="sec_9f2a1c40_000_002",
                        number="5.3",
                        title="TCP 拥塞控制",
                        seq=2,
                        knowledge_point_count=6,
                    ),
                ],
            )
        ],
    )


def _mock_questions(material_id: str) -> list[QuestionOut]:
    return [
        QuestionOut(
            id="q_9f2a1c40_001",
            material_id=material_id,
            source_page=11,
            source_block_id=block_id(material_id, 3),
            question_type="single_choice",
            stem_md="下列关于 TCP 拥塞控制的说法，正确的是：",
            options_json='[{"key":"A","content":"cwnd 由接收方通告"},'
            '{"key":"B","content":"慢启动阶段 cwnd 指数增长"}]',
            answer_md="B",
            answer_missing=False,
            extraction_confidence=0.93,
            pk_kp_id="kp_9f2a1c40_000_002_003",
        ),
        QuestionOut(
            id="q_9f2a1c40_002",
            material_id=material_id,
            source_page=12,
            source_block_id=None,
            question_type="short_answer",
            stem_md="简述超时重传时 cwnd 如何变化。",
            options_json=None,
            answer_md=None,
            answer_missing=True,  # ★ 材料里确实没给答案 —— 对应「存疑处」
            extraction_confidence=0.81,
            pk_kp_id=None,
        ),
    ]


def _mock_markdown(material_id: str) -> str:
    lines = [
        f"<!-- material: {material_id} -->",
        "",
        "# 第 5 章 传输层",
        "",
        "## 5.3 TCP 拥塞控制",
        "",
        "拥塞窗口 `cwnd` 的大小由发送方根据网络拥塞程度动态调整。",
        "",
    ]
    return "\n".join(lines)


def _job_in_progress(db: Session, target_id: str) -> bool:
    """同一资源已有任务在跑 → 409。

    mock 模式下也走真实查询 —— 这是"错误的正确性"，不该被 mock 掉。
    """
    stmt = select(Job.id).where(Job.target_id == target_id, Job.status.in_(("queued", "running")))
    return db.execute(stmt).first() is not None


# ---------------------------------------------------------------------------
# 端点 4：上传（POST /api/materials）
# ---------------------------------------------------------------------------


@router.post(
    "/materials",
    response_model=Envelope[UploadResultOut],
    status_code=202,
    summary="上传素材",
    description=(
        "支持一次上传多个文件。**部分文件被拒绝时仍返回 202**，"
        "`rejected` 数组给出可读原因，不得整批失败。"
    ),
)
async def upload_materials(
    db: DbSession,
    files: Annotated[list[UploadFile], File(description="待解析的文件，可多个")],
) -> Envelope[UploadResultOut]:
    accepted: list[UploadAcceptedOut] = []
    rejected: list[UploadRejectedOut] = []
    max_bytes = settings.max_upload_mb * 1024 * 1024

    for f in files:
        name = f.filename or "未命名文件"
        ext = _ext_of(name)

        if ext not in SUPPORTED_EXTENSIONS:
            rejected.append(
                UploadRejectedOut(
                    filename=name,
                    reason=(
                        f"暂不支持 {ext or '未知'} 格式，请转为 PDF、DOCX、PPTX 或图片（JPG/PNG）"
                    ),
                )
            )
            continue

        content = await f.read()
        if len(content) > max_bytes:
            rejected.append(
                UploadRejectedOut(
                    filename=name,
                    reason=(
                        f"文件 {len(content) / 1024 / 1024:.1f}MB 超出 "
                        f"{settings.max_upload_mb}MB 限制，请压缩后再上传"
                    ),
                )
            )
            continue

        # ★ 素材 id 由**文件内容 hash** 决定 —— 同一文件重复上传得到同一个 id，
        #   配合 materials.file_hash 的唯一索引，天然做到「重复上传不重复抽取」（成本控制 C2）
        mat_id = make_material_id(hash_bytes(content))
        accepted.append(
            UploadAcceptedOut(material_id=mat_id, filename=name, job_id=f"job_{mat_id[4:12]}")
        )

    if not accepted and not rejected:
        raise ApiError(ErrorCode.INVALID_PARAM, "没有收到任何文件")

    return ok(UploadResultOut(accepted=accepted, rejected=rejected))


# ---------------------------------------------------------------------------
# 端点 5：清单（GET /api/materials）
# ---------------------------------------------------------------------------


@router.get(
    "/materials",
    response_model=Envelope[PageData[MaterialItemOut]],
    summary="素材清单",
    description="分页 + 按状态过滤。这是「素材工作台」页的数据源。",
)
def list_materials(
    db: DbSession,
    page: PageDep,
    status: Annotated[str | None, Query(description="按解析状态过滤")] = None,
) -> Envelope[PageData[MaterialItemOut]]:
    if status is not None and status not in MATERIAL_STATUSES:
        raise ApiError(
            ErrorCode.INVALID_PARAM,
            f"status 取值不合法：{status}",
            {"allowed": list(MATERIAL_STATUSES)},
        )

    if MOCK_MODE:
        items = [_mock_material()]
        return ok(PageData.of(items=items, total=1, params=page))

    stmt = select(Material).order_by(Material.created_at.desc())
    if status is not None:
        stmt = stmt.where(Material.status == status)
    total = len(db.execute(stmt).scalars().all())
    rows = db.execute(stmt.offset(page.offset).limit(page.limit)).scalars().all()
    items = [
        MaterialItemOut(
            id=m.id,
            filename=m.filename,
            mime_type=m.mime_type,
            size_bytes=m.size_bytes,
            source_type=m.source_type,
            parse_method=m.parse_method,
            status=m.status,
            page_count=m.page_count,
            duration_sec=m.duration_sec,
            char_count=m.char_count,
            quality_score=m.quality_score,
            created_at=m.created_at,
        )
        for m in rows
    ]
    return ok(PageData.of(items=items, total=total, params=page))


# ---------------------------------------------------------------------------
# 端点 6：详情（GET /api/materials/{id}）
# ---------------------------------------------------------------------------


@router.get(
    "/materials/{material_id}",
    response_model=Envelope[MaterialItemOut],
    summary="素材详情",
    description="结构同清单项（api-spec §3.3 注明「同 3.2 结构」）。",
)
def get_material(material_id: str, db: DbSession) -> Envelope[MaterialItemOut]:
    mat = _require_material(material_id, db)
    if mat is None:
        return ok(_mock_material(material_id))
    return ok(
        MaterialItemOut(
            id=mat.id,
            filename=mat.filename,
            mime_type=mat.mime_type,
            size_bytes=mat.size_bytes,
            source_type=mat.source_type,
            parse_method=mat.parse_method,
            status=mat.status,
            page_count=mat.page_count,
            duration_sec=mat.duration_sec,
            char_count=mat.char_count,
            quality_score=mat.quality_score,
            created_at=mat.created_at,
        )
    )


# ---------------------------------------------------------------------------
# 端点 7：解析块（GET /api/materials/{id}/blocks）
# ---------------------------------------------------------------------------


@router.get(
    "/materials/{material_id}/blocks",
    response_model=Envelope[list[BlockOut]],
    summary="解析块列表",
    description="Markdown 预览与高亮定位的数据源。可按页码与块类型过滤。",
)
def list_blocks(
    material_id: str,
    db: DbSession,
    page_no: Annotated[int | None, Query(ge=1, description="按页码过滤")] = None,
    block_type: Annotated[str | None, Query(description="按块类型过滤")] = None,
) -> Envelope[list[BlockOut]]:
    _require_material(material_id, db)
    wanted = _parse_block_type(block_type)

    if MOCK_MODE:
        blocks = _mock_blocks(material_id)
    else:
        blocks = []  # D6：从 material_blocks 真实查询

    if page_no is not None:
        blocks = [b for b in blocks if b.page_no == page_no]
    if wanted is not None:
        blocks = [b for b in blocks if b.block_type == wanted]
    return ok(blocks)


# ---------------------------------------------------------------------------
# 端点 8：整篇 Markdown（GET /api/materials/{id}/markdown）★ 非 JSON 响应
# ---------------------------------------------------------------------------


@router.get(
    "/materials/{material_id}/markdown",
    summary="整篇 Markdown",
    description=(
        "返回拼接后的整篇 Markdown（`text/markdown`）。\n\n"
        "**这是非 JSON 响应**：请求标识走 `X-Request-ID` 响应头；"
        "出错时仍返回 JSON 包封（api-spec §1.1 的非 JSON 例外条款）。"
    ),
    response_class=MarkdownResponse,
)
def get_markdown(material_id: str, db: DbSession):
    _require_material(material_id, db)
    return text_response(_mock_markdown(material_id), "text/markdown; charset=utf-8")


# ---------------------------------------------------------------------------
# 端点 9：章节大纲（GET /api/materials/{id}/outline）
# ---------------------------------------------------------------------------


@router.get(
    "/materials/{material_id}/outline",
    response_model=Envelope[OutlineOut],
    summary="章节骨架",
    description="章 → 节的骨架，是**未抽知识点时的中间态**，也是校验三级结构完整率的对象。",
)
def get_outline(material_id: str, db: DbSession) -> Envelope[OutlineOut]:
    _require_material(material_id, db)
    return ok(_mock_outline(material_id))


# ---------------------------------------------------------------------------
# 端点 10：题目列表（GET /api/materials/{id}/questions）
# ---------------------------------------------------------------------------


@router.get(
    "/materials/{material_id}/questions",
    response_model=Envelope[list[QuestionOut]],
    summary="素材抽出的题目",
    description=(
        "从该素材抽出的**原始题目**。注意 `answer_missing=true` 表示材料里就没给答案 —— "
        "这是 Stage 1「存疑处」的对外体现，不伪装成完整数据。"
    ),
)
def list_questions(material_id: str, db: DbSession) -> Envelope[list[QuestionOut]]:
    _require_material(material_id, db)
    return ok(_mock_questions(material_id))


# ---------------------------------------------------------------------------
# 端点 11：重新解析（POST /api/materials/{id}/reparse）
# ---------------------------------------------------------------------------


@router.post(
    "/materials/{material_id}/reparse",
    response_model=Envelope[ReparseAcceptedOut],
    status_code=202,
    summary="重新解析",
    description="失败隔离：某份素材解析失败可单独重试。同一素材已有任务在跑时返回 409。",
)
def reparse_material(material_id: str, db: DbSession) -> Envelope[ReparseAcceptedOut]:
    _require_material(material_id, db)
    if _job_in_progress(db, material_id):
        raise ApiError(ErrorCode.JOB_IN_PROGRESS)
    return ok(ReparseAcceptedOut(material_id=material_id, job_id=f"job_re_{material_id[4:12]}"))


# ---------------------------------------------------------------------------
# 端点 12：删除（DELETE /api/materials/{id}）
# ---------------------------------------------------------------------------


@router.delete(
    "/materials/{material_id}",
    response_model=Envelope[dict],
    summary="删除素材",
    description="删除素材及其级联数据（解析块 / 章节 / 知识点 / 题目）。",
)
def delete_material(material_id: str, db: DbSession) -> Envelope[dict]:
    mat = _require_material(material_id, db)
    if mat is not None:
        # 级联由数据库的 ON DELETE CASCADE 负责（data-model.md §0）
        db.delete(mat)
        db.commit()
    return ok({"deleted": material_id})
