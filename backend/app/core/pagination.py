"""分页约定（归属：P2，三人共用）。对应 docs/api-spec.md §1.3。

**默认值与越界行为必须写死在契约里**（v1.3 补充）。否则前端会按自己猜的默认值
写死分页控件，而 mock 与真实实现又可能不一致 —— 这类偏差要到联调才暴露。
"""

from __future__ import annotations

from typing import Generic, TypeVar

from fastapi import Query
from pydantic import BaseModel, Field

from app.core.errors import ApiError, ErrorCode

T = TypeVar("T")

DEFAULT_PAGE = 1
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


class PageParams(BaseModel):
    """分页参数。用 `Depends(PageParams.as_dependency)` 注入路由。

    越界一律 `400 INVALID_PARAM` —— 不做静默夹取（把 `page_size=999` 悄悄改成 100
    会让调用方以为自己拿到了全部数据）。
    """

    page: int = Field(default=DEFAULT_PAGE, ge=1)
    page_size: int = Field(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)

    @classmethod
    def as_dependency(
        cls,
        page: int = Query(DEFAULT_PAGE, ge=1, description="页码，从 1 开始"),
        page_size: int = Query(
            DEFAULT_PAGE_SIZE,
            ge=1,
            le=MAX_PAGE_SIZE,
            description=f"每页条数，1–{MAX_PAGE_SIZE}",
        ),
    ) -> PageParams:
        """FastAPI 依赖工厂。

        自己先校验再交给 FastAPI：这样越界返回的是我们的 `INVALID_PARAM`
        （中文 message），而不是 FastAPI 默认那套英文的 422 校验错误。
        """
        if page < 1:
            raise ApiError(ErrorCode.INVALID_PARAM, "页码必须从 1 开始")
        if page_size < 1 or page_size > MAX_PAGE_SIZE:
            raise ApiError(ErrorCode.INVALID_PARAM, f"每页条数必须在 1 到 {MAX_PAGE_SIZE} 之间")
        return cls(page=page, page_size=page_size)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        return self.page_size


class PageData(BaseModel, Generic[T]):
    """分页响应体（api-spec §1.3）：`{ items, total, page, page_size }`。"""

    items: list[T] = Field(default_factory=list)
    total: int = 0
    page: int = DEFAULT_PAGE
    page_size: int = DEFAULT_PAGE_SIZE

    @classmethod
    def of(cls, items: list[T], total: int, params: PageParams) -> PageData[T]:
        return cls(items=items, total=total, page=params.page, page_size=params.page_size)
