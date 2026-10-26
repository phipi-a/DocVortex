"""公开共享渲染片段操作，供宿主组合专用输出而不依赖私有模块。"""

from __future__ import annotations

from dataclasses import dataclass

from ..options import LatexDelimitersConfig
from ..schema import ImagePayloadBlock, InlineSpan
from ._internal.common.list_items import ListItem, ListItemKind, OrderedListStyle


@dataclass(frozen=True)
class InlineEmission:
    """输出 [start, end) 由 path 处的 Span 产生。

    path 从 content 下标开始，超链接子节点追加子下标。source_start/source_end 是叶子 Span
    content 中被渲染的字符区间（含其转义）；样式、公式分隔符、代码 fence 与链接语法等
    包装符号没有字符区间，为 None。
    """

    path: tuple[int, ...]
    start: int
    end: int
    source_start: int | None = None
    source_end: int | None = None


@dataclass(frozen=True)
class TracedInlineContent:
    """行内 Markdown 及其按输出顺序排列、首尾相接覆盖全部输出的来源区间。"""

    markdown: str
    emissions: tuple[InlineEmission, ...]

    def span_range(self, path: tuple[int, ...]) -> tuple[int, int] | None:
        """返回 path 处 Span（含其包装符号与子节点）的完整输出区间；无输出时为 None。"""
        owned = [item for item in self.emissions if item.path[: len(path)] == path]
        if not owned:
            return None
        return owned[0].start, owned[-1].end

    def source_range(self, path: tuple[int, ...], start: int, end: int) -> tuple[int, int] | None:
        """返回叶子 Span content[start:end] 的输出区间（含字符转义，不含包装符号）。

        边界落在一次多对一改写内部（例如行内代码中的 CRLF）时返回 None。
        """
        if not start < end:
            raise ValueError("source range must not be empty")
        first = last = None
        for item in self.emissions:
            if item.path != path or item.source_start is None or item.source_end is None:
                continue
            verbatim = item.end - item.start == item.source_end - item.source_start
            if first is None and item.source_start <= start < item.source_end:
                if item.source_start != start and not verbatim:
                    return None
                first = item.start + (start - item.source_start)
            if item.source_start < end <= item.source_end:
                if item.source_end != end and not verbatim:
                    return None
                last = item.end - (item.source_end - end)
        if first is None or last is None:
            return None
        return first, last


def render_inline_content(
    content: list[InlineSpan],
    delimiters: LatexDelimitersConfig,
    *,
    pure_markdown: bool = False,
) -> str:
    """将行内语义编码为 Markdown，沿用共享的样式与公式规则；pure_markdown 禁止 raw HTML。"""
    from ._internal.markdown.dialect import markdown_dialect
    from ._internal.markdown.inline import render_inline_content as render_value

    if not isinstance(pure_markdown, bool):
        raise TypeError("pure_markdown must be a bool")
    with markdown_dialect(pure=pure_markdown):
        return render_value(content, delimiters)


def trace_inline_content(
    content: list[InlineSpan],
    delimiters: LatexDelimitersConfig,
    *,
    pure_markdown: bool = False,
) -> TracedInlineContent:
    """与 render_inline_content 输出相同的 Markdown，并给出每段输出来自哪个 Span 的哪些字符。"""
    from ._internal.markdown.dialect import markdown_dialect
    from ._internal.markdown.inline import trace_inline_content as trace_value

    if not isinstance(pure_markdown, bool):
        raise TypeError("pure_markdown must be a bool")
    with markdown_dialect(pure=pure_markdown):
        pieces = trace_value(content, delimiters)
    emissions: list[InlineEmission] = []
    cursor = 0
    for piece in pieces:
        start, end = cursor, cursor + len(piece.text)
        cursor = end
        source = piece.source
        previous = emissions[-1] if emissions else None
        # 只合并逐字符一对一的输出，区间内部偏移因此可以直接换算。
        if previous is not None and previous.path == piece.path:
            if source is None and previous.source_start is None:
                emissions[-1] = InlineEmission(piece.path, previous.start, end)
                continue
            if (
                source is not None
                and previous.source_end == source[0]
                and previous.end - previous.start == previous.source_end - previous.source_start
                and end - start == source[1] - source[0] == 1
            ):
                emissions[-1] = InlineEmission(piece.path, previous.start, end, previous.source_start, source[1])
                continue
        emissions.append(InlineEmission(piece.path, start, end, *(source or (None, None))))
    return TracedInlineContent("".join(piece.text for piece in pieces), tuple(emissions))


def render_internal_link(label: str, anchor: str) -> str:
    """构造与共享 Markdown renderer 一致的内部链接。"""
    from ._internal.markdown.inline import render_internal_link as render_value

    return render_value(label, anchor)


def resolve_image_source(block: ImagePayloadBlock, asset_base_url: str = "") -> str | None:
    """按既有素材优先级解析图片引用，不写出文件。"""
    from ._internal.markdown.assets import resolve_image_source as resolve_value

    return resolve_value(block, asset_base_url)


def normalize_image_source(source: str) -> str:
    """规范化素材路径，保持共享渲染器的 URL 与路径处理行为。"""
    from ._internal.markdown.assets import normalize_image_source as normalize_value

    return normalize_value(source)


def format_embedded_html(markup: str, *, asset_base_url: str, delimiters: LatexDelimitersConfig) -> str:
    """复用嵌入 HTML 的图片地址和公式分隔符处理。"""
    from ._internal.markdown.table import format_embedded_html as format_value

    return format_value(markup, asset_base_url=asset_base_url, delimiters=delimiters)


def strip_index_page_tail(content: list[InlineSpan]) -> list[InlineSpan]:
    """剥离目录尾部页码，保持行内样式和链接语义。"""
    from ._internal.common.index import strip_index_page_tail as strip_value

    return strip_value(content)


def parse_list_item_marker(content: list[InlineSpan]) -> ListItem:
    """解析列表标记并返回共享的不可变条目描述。"""
    from ._internal.common.list_items import parse_list_item_marker as parse_value

    return parse_value(content)


__all__ = [
    "InlineEmission",
    "ListItem",
    "ListItemKind",
    "OrderedListStyle",
    "TracedInlineContent",
    "format_embedded_html",
    "normalize_image_source",
    "parse_list_item_marker",
    "render_inline_content",
    "render_internal_link",
    "resolve_image_source",
    "strip_index_page_tail",
    "trace_inline_content",
]
