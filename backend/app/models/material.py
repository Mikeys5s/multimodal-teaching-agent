"""素材与解析块（归属：P2）。对应 docs/data-model.md §2.1 / §2.2。

`material_blocks` 是**溯源的原子单位** —— 知识点里的 `source_quote`、
依赖边里的 `evidence_quote`，最终都要能定位到这里的某一行。所以它的
页码 / 行号锚点字段不是可选的装饰，而是验收项 A1-6 / A2-3 的载体。
"""

from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models._common import (
    BLOCK_TYPES,
    MATERIAL_STATUSES,
    PARSE_METHODS,
    SOURCE_TYPES,
    sql_in,
    utc_iso_check,
    utc_now_iso,
    utc_server_default,
)


class Material(Base):
    """一行一份用户上传的原始文件。"""

    __tablename__ = "materials"

    id: Mapped[str] = mapped_column(
        Text, primary_key=True, doc="mat_<文件内容 sha256 前 8 位>，确定性 ID"
    )
    filename: Mapped[str] = mapped_column(Text, nullable=False, doc="原始文件名")
    file_hash: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        unique=True,
        doc="文件内容 SHA-256 全串。成本控制 C2：同一文件重复上传不重复抽取；也是 id 的生成依据",
    )
    stored_path: Mapped[str] = mapped_column(Text, nullable=False, doc="相对 UPLOAD_DIR 的落盘路径")
    mime_type: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)

    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    parse_method: Mapped[str | None] = mapped_column(Text, nullable=True, doc="实际使用的方式")

    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'pending'"))
    error_message: Mapped[str | None] = mapped_column(
        Text, nullable=True, doc="失败原因，面向用户的文案"
    )

    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_sec: Mapped[int | None] = mapped_column(
        Integer, nullable=True, doc="音频时长；字段保留，初赛不启用（D-08）"
    )
    char_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    uncertain_notes: Mapped[str | None] = mapped_column(
        Text, nullable=True, doc="存疑处 JSON 数组（§3.1）。显式不确定性，不伪装完美"
    )
    quality_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    # 时间字段三层防护：ORM 默认值 + 数据库默认值 + CHECK 格式校验。
    # 只靠"约定大家记得手传 utc_now_iso()"是不够的 —— 漏传会报错，
    # 但传错格式不会，而错格式会静默破坏按时间排序。
    created_at: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default=utc_now_iso,
        server_default=utc_server_default(),
    )
    updated_at: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default=utc_now_iso,
        onupdate=utc_now_iso,  # ORM 层更新时自动刷新
        server_default=utc_server_default(),
    )

    __table_args__ = (
        CheckConstraint(f"source_type IN ({sql_in(SOURCE_TYPES)})", name="source_type"),
        # parse_method 可为空（还没解析），非空时必须在白名单内
        CheckConstraint(
            f"parse_method IS NULL OR parse_method IN ({sql_in(PARSE_METHODS)})",
            name="parse_method",
        ),
        CheckConstraint(f"status IN ({sql_in(MATERIAL_STATUSES)})", name="status"),
        CheckConstraint(utc_iso_check("created_at"), name="created_at_utc_iso"),
        CheckConstraint(utc_iso_check("updated_at"), name="updated_at_utc_iso"),
        Index("idx_materials_status", "status"),
        # 刻意用普通升序索引，不写 DESC —— 两个理由：
        #   ① SQLite 可以**双向**遍历索引，DESC 索引不带来任何查询收益；
        #   ② `text("created_at DESC")` 这种表达式索引 Alembic 的 autogenerate
        #      识别不了，会**静默漏掉**（实测踩过），导致迁移与模型不一致。
        Index("idx_materials_created", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<Material {self.id} {self.filename!r} status={self.status}>"


class MaterialBlock(Base):
    """解析后的最小 Markdown 单元 —— 一切溯源的终点。"""

    __tablename__ = "material_blocks"

    id: Mapped[str] = mapped_column(Text, primary_key=True, doc="blk_<材料hash8>_<seq:05d>")
    material_id: Mapped[str] = mapped_column(
        Text, ForeignKey("materials.id", ondelete="CASCADE"), nullable=False
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False, doc="文档内顺序，从 0 开始")

    # ---- 定位锚点：溯源必须落到具体位置，否则"引用原文"无法核对 ----
    page_no: Mapped[int | None] = mapped_column(Integer, nullable=True, doc="页码，1-based")
    ts_start_ms: Mapped[int | None] = mapped_column(
        Integer, nullable=True, doc="音频起始毫秒；保留不启用（D-08）"
    )
    ts_end_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    line_start: Mapped[int | None] = mapped_column(Integer, nullable=True, doc="页内起始行号")
    line_end: Mapped[int | None] = mapped_column(Integer, nullable=True)

    block_type: Mapped[str] = mapped_column(Text, nullable=False)
    heading_level: Mapped[int | None] = mapped_column(
        Integer, nullable=True, doc="1–6，仅 heading 有值"
    )
    content_md: Mapped[str] = mapped_column(Text, nullable=False, doc="Markdown 内容")

    image_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    bbox: Mapped[str | None] = mapped_column(
        Text, nullable=True, doc="版面坐标 JSON [x1,y1,x2,y2]，用于高亮定位"
    )
    ocr_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    __table_args__ = (
        UniqueConstraint("material_id", "seq", name="uq_blocks_material_seq"),
        CheckConstraint(f"block_type IN ({sql_in(BLOCK_TYPES)})", name="block_type"),
        # heading_level 只在 heading 块上有意义，且必须是 1–6
        CheckConstraint(
            "heading_level IS NULL OR (heading_level BETWEEN 1 AND 6)",
            name="heading_level_range",
        ),
        CheckConstraint("seq >= 0", name="seq_non_negative"),
        Index("idx_blocks_material_seq", "material_id", "seq"),
    )

    def __repr__(self) -> str:
        return f"<MaterialBlock {self.id} type={self.block_type} seq={self.seq}>"
