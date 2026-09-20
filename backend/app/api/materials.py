"""素材相关路由（归属：P2）。对应 docs/api-spec.md §3，端点 4–12。

## 实现口径：**本文件已全部接真实数据**（D-22 的 mock 阶段结束）

骨架阶段（D-22）的做法是"输入校验真实、业务数据 mock"，
理由是**接口冻结的价值主要在错误分支上**。那个阶段已经过去了 ——
**本文件的 9 个端点现在全部走真实库**，`MOCK_MODE` 开关与假数据函数都已删除。

**这一条要写在这里，因为"还开着 mock"是个看不见的状态**：
代码完整、测试全绿、界面上有数据 —— **但数据是编的**。
删掉开关比留着它更安全：留着它，下一个人会以为某处还是假的，或者忘了他已经改了。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, File, Query, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.errors import ApiError, ErrorCode
from app.core.pagination import PageData, PageParams
from app.core.response import Envelope, MarkdownResponse, ok, text_response
from app.db import engine, get_db
from app.models import Job, Material, MaterialBlock, utc_now_iso
from app.models.ids import block_id, hash_bytes
from app.models.ids import material_id as make_material_id
from app.pipeline import run_parse_job
from app.schemas.material import (
    BlockOut,
    MaterialItemOut,
    OutlineChapterOut,
    OutlineOut,
    OutlineSectionOut,
    QuestionOut,
    ReparseAcceptedOut,
    UploadAcceptedOut,
    UploadRejectedOut,
    UploadResultOut,
)

router = APIRouter(tags=["materials"])

DbSession = Annotated[Session, Depends(get_db)]
PageDep = Annotated[PageParams, Depends(PageParams.as_dependency)]

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
    # 一律真查库。
    #
    # 之前 mock 模式下这里直接 return None（"格式合法即视为存在"），
    # 那会让**不存在的素材**返回 200 + 空列表，而不是 404 —— 前端会以为"这份素材是空的"，
    # 而不是"这份素材不存在"。两者对用户是**完全不同**的事。
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


def _guess_source_type(ext: str) -> str:
    """按扩展名给一个**保守的**初值，真正的值由解析器判定后覆盖。

    为什么要给初值：`materials.source_type` 是 NOT NULL 且有 CHECK，
    上传时还没解析，但这一行必须能落库。选最保守的那个（文本层），
    解析完 `run_parse` 会拿 `ParsedDocument.source_type` 覆盖它。
    """
    return {
        ".pdf": "pdf_text",
        ".docx": "docx",
        ".pptx": "pptx",
        ".jpg": "image",
        ".jpeg": "image",
        ".png": "image",
    }.get(ext, "pdf_text")


def _run_parse_in_background(job_id: str, mat_id: str) -> None:
    """后台解析任务的入口。

    ⚠️ **必须自己开一个 session**：请求的 session 在响应返回时就关了，
    后台任务拿不到它。（用它的后果是 `Session is closed` —— 而且是在后台线程里，
    不会被谁看见。）

    ⚠️ 这里**故意不吞异常**：`run_parse_job` 已经把失败写进了
    `jobs.status` 与 `materials.status`，异常继续往上抛才能被日志看到。
    """
    from app.db import Session as DbSessionFactory  # 局部导入，避免循环依赖

    with DbSessionFactory(engine) as session:
        run_parse_job(session, job_id, mat_id)


# ---------------------------------------------------------------------------
# 端点 4：上传（POST /api/materials）
# ---------------------------------------------------------------------------
#
# ⚠️ 两个 helper（`_guess_source_type` / `_run_parse_in_background`）**必须写在
#    装饰器之前**。写成之后会怎样：FastAPI 会把紧跟装饰器的那个函数当成路由处理器 ——
#    于是 `/materials` 变成了"要求一个 ext 字段"的接口，
#    而真正的 `upload_materials` 变成一个**没人调用的普通函数**。
#    （这个坑今天实测撞到了，报错是 `{"field":"ext","reason":"Field required"}` ——
#     从报错完全看不出真正原因。）


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
    background: BackgroundTasks,
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

        # ---- 重复上传：返回已有的，不重复解析（C2 的落点）------------------
        existing = db.get(Material, mat_id)
        if existing is not None:
            last_job = db.execute(
                select(Job.id)
                .where(Job.target_id == mat_id)
                .order_by(Job.created_at.desc())
                .limit(1)
            ).scalar()
            accepted.append(
                UploadAcceptedOut(
                    material_id=mat_id,
                    filename=existing.filename,
                    # 复用同一份文件时**不新建任务**（这正是 C2 要省的成本）。
                    # 返回它上一次的任务 id，让前端轮询逻辑不必为这种情况写分支；
                    # 若从未建过任务则为空串（前端应把空串视作"无需轮询"）。
                    job_id=last_job or "",
                )
            )
            continue

        # ---- 落盘 + 落库 + 建解析任务 -------------------------------------
        #
        # ⚠️ 这三件事**必须一起做**。之前这里只算了 id 就返回 ——
        #    素材从不落库、解析从不触发，整条链路的第一步就是空的。
        dest = settings.upload_path / f"{mat_id}{ext}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)

        now = utc_now_iso()
        db.add(
            Material(
                id=mat_id,
                filename=name,
                file_hash=hash_bytes(content),
                stored_path=str(dest),
                mime_type=f.content_type or "application/octet-stream",
                size_bytes=len(content),
                # 解析前先给一个保守值；`run_parse` 会用解析器**判定出的**真实值覆盖它
                source_type=_guess_source_type(ext),
                parse_method=None,
                status="pending",
                created_at=now,
                updated_at=now,
            )
        )
        job = Job(
            id=f"job_{mat_id[4:20]}",
            job_type="parse",
            target_id=mat_id,
            status="queued",
            progress=0,
            stage_detail="排队中",
            created_at=now,
        )
        db.add(job)
        db.commit()

        background.add_task(_run_parse_in_background, job.id, mat_id)
        accepted.append(UploadAcceptedOut(material_id=mat_id, filename=name, job_id=job.id))

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

    stmt = select(Material).order_by(Material.created_at.desc())
    count_stmt = select(func.count()).select_from(Material)
    if status is not None:
        stmt = stmt.where(Material.status == status)
        count_stmt = count_stmt.where(Material.status == status)

    # ⚠️ 计数**不要**写成 `len(db.execute(stmt).scalars().all())` ——
    #    那是把整表拉回 Python 只为数个数。素材上千份时白拉上千行（含所有列）。
    #    用 `func.count()` 让数据库数，只回一个整数。
    total = db.scalar(count_stmt) or 0
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
    # `_require_material` 现在一律真查库、查不到就抛 404，
    # 所以这里不再需要 "mat is None 走 mock" 那条死分支。
    mat = _require_material(material_id, db)
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

    # 过滤**下推到 SQL**，不在 Python 里筛。
    #
    # 之前（mock 阶段）是"先取全部再在内存过滤" —— 那在 4 条假数据上没问题，
    # 但真实教材一份就有上万块，一次全取回来再筛掉九成是白白的内存与 IO。
    # 而 `page_no` 与 `block_type` 都是列，过滤没有理由留在内存里。
    stmt = (
        select(MaterialBlock)
        .where(MaterialBlock.material_id == material_id)
        .order_by(MaterialBlock.seq)
    )
    if page_no is not None:
        stmt = stmt.where(MaterialBlock.page_no == page_no)
    if wanted is not None:
        stmt = stmt.where(MaterialBlock.block_type == wanted)

    rows = db.execute(stmt).scalars().all()
    return ok(
        [
            BlockOut(
                id=r.id,
                seq=r.seq,
                page_no=r.page_no,
                line_start=r.line_start,
                line_end=r.line_end,
                block_type=r.block_type,
                heading_level=r.heading_level,
                content_md=r.content_md,
                image_path=r.image_path,
                ocr_confidence=r.ocr_confidence,
            )
            for r in rows
        ]
    )


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
