"""SQLAlchemy 数据模型（归属：P2）。

⚠️ 新增模型文件后**必须在本文件里 import 它**，否则 Alembic 的 autogenerate
看不到该表，会生成一个空迁移 —— 这是最容易白忙半小时的坑。

本模块同时重新导出 `Base`，让 `from app.models import Base` 这类写法可用。
"""

from app.db import Base
from app.models._common import utc_now_iso
from app.models.ids import (
    block_id,
    chapter_id,
    hash_bytes,
    hash_file,
    knowledge_point_id,
    material_id,
    section_id,
)
from app.models.knowledge import KnowledgePoint, KpPrerequisite
from app.models.material import Material, MaterialBlock
from app.models.outline import Chapter, Section

__all__ = [
    # 基类
    "Base",
    # 模型
    "Material",
    "MaterialBlock",
    "Chapter",
    "Section",
    "KnowledgePoint",
    "KpPrerequisite",
    # ID 生成（确定性 ID，见 docs/data-model.md §0）
    "material_id",
    "block_id",
    "chapter_id",
    "section_id",
    "knowledge_point_id",
    "hash_bytes",
    "hash_file",
    # 工具
    "utc_now_iso",
]
