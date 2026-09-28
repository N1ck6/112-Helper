from __future__ import annotations

from collections.abc import Sequence
from typing import Generic, TypeVar

from fastapi import Query
from pydantic import BaseModel

T = TypeVar("T")

MAX_PAGE_SIZE = 200


class PageParams:
    def __init__(
        self,
        page: int = Query(1, ge=1, description="Номер страницы, начиная с 1"),
        size: int = Query(50, ge=1, le=MAX_PAGE_SIZE, description="Размер страницы"),
    ) -> None:
        self.page = page
        self.size = size

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.size

    @property
    def limit(self) -> int:
        return self.size


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    size: int
    pages: int


def build_page(items: Sequence[T], total: int, params: PageParams) -> Page[T]:
    pages = (total + params.size - 1) // params.size if total else 0
    return Page[T](items=list(items), total=total, page=params.page, size=params.size, pages=pages)
