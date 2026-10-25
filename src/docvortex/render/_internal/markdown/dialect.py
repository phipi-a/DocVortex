"""Markdown 方言开关：在一次渲染调用内选择 HTML 增强或纯 GFM 输出。"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

_pure_markdown: ContextVar[bool] = ContextVar("docvortex_pure_markdown", default=False)


@contextmanager
def markdown_dialect(*, pure: bool) -> Iterator[None]:
    """限定纯 Markdown 模式的调用范围，异常和重入后均恢复外层设置。"""
    token = _pure_markdown.set(pure)
    try:
        yield
    finally:
        _pure_markdown.reset(token)


def is_pure_markdown() -> bool:
    """当前渲染是否禁止输出任何 raw HTML。"""
    return _pure_markdown.get()


__all__ = ["is_pure_markdown", "markdown_dialect"]
