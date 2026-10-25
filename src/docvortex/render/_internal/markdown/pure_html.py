"""纯 Markdown 模式下把嵌入 HTML 降级为 GFM：表格拍平，未知标签只保留文字。"""

from __future__ import annotations

import re
from collections.abc import Iterable

from bs4 import BeautifulSoup
from bs4.element import NavigableString, PageElement, PreformattedString, Tag

from ....options import LatexDelimitersConfig
from .assets import build_markdown_image
from .escaping import escape_conservative_markdown_text, escape_text_block_markdown_prefix
from .inline import render_styled_markdown_text
from .table import (
    _STYLE_TAGS,
    _escape_cell_text,
    _escape_gfm_formula_pipes,
    _escape_link_url,
    _format_markdown_row,
    _normalize_cell_text,
    _render_inline_code,
)

_DROPPED_TAGS = frozenset(
    {
        "audio",
        "button",
        "canvas",
        "embed",
        "form",
        "head",
        "iframe",
        "input",
        "link",
        "meta",
        "noscript",
        "object",
        "script",
        "select",
        "style",
        "template",
        "textarea",
        "title",
        "video",
    }
)
_BLOCK_TAGS = frozenset(
    {
        "address",
        "article",
        "aside",
        "blockquote",
        "caption",
        "dd",
        "details",
        "div",
        "dl",
        "dt",
        "figcaption",
        "figure",
        "footer",
        "header",
        "hr",
        "li",
        "main",
        "nav",
        "ol",
        "p",
        "pre",
        "section",
        "summary",
        "table",
        "tbody",
        "td",
        "tfoot",
        "th",
        "thead",
        "tr",
        "ul",
    }
)
_HEADING_RE = re.compile(r"h[1-6]")
_MAX_SPAN = 1000


def html_to_pure_markdown(markup: str, delimiters: LatexDelimitersConfig) -> str:
    """把嵌入 HTML 片段转换为不含 raw HTML 的 Markdown 块序列。"""
    soup = BeautifulSoup(markup, "html.parser")
    if soup.find() is None:
        # 无标签的识别文本保持既有原样输出。
        return markup
    return "\n\n".join(_render_blocks(soup.children, delimiters))


def _render_blocks(children: Iterable[PageElement], delimiters: LatexDelimitersConfig) -> list[str]:
    """按块级标签切分段落，连续行内节点合并为一个段落。"""
    blocks: list[str] = []
    run: list[PageElement] = []

    def flush() -> None:
        """把累积的行内节点输出为一个段落，并转义行首块标记。"""
        text = _render_inline(run, delimiters, in_table=False)
        lines = [escape_text_block_markdown_prefix(line.strip()) for line in text.split("\n")]
        paragraph = "\n".join(line for line in lines if line)
        if paragraph:
            blocks.append(paragraph)
        run.clear()

    for child in children:
        if not isinstance(child, Tag):
            run.append(child)
            continue
        name = child.name
        if name in _DROPPED_TAGS:
            continue
        if name == "table":
            flush()
            blocks.append(flatten_html_table(child, delimiters))
        elif name == "pre":
            flush()
            blocks.append(_fenced(child.get_text()))
        elif name in {"ul", "ol"}:
            flush()
            blocks.append("\n".join(_render_list(child, delimiters, 0)))
        elif _HEADING_RE.fullmatch(name):
            flush()
            title = _collapse_lines(_render_inline(child.children, delimiters, in_table=False))
            if title:
                blocks.append(f"{'#' * int(name[1])} {title}")
        elif name == "hr":
            flush()
            blocks.append("---")
        elif name in _BLOCK_TAGS:
            flush()
            blocks.extend(_render_blocks(child.children, delimiters))
        else:
            run.append(child)
    flush()
    return [block for block in blocks if block.strip()]


def _render_list(node: Tag, delimiters: LatexDelimitersConfig, depth: int) -> list[str]:
    """渲染 HTML 列表，有序列表保留 start 起始编号，嵌套列表缩进四格。"""
    ordered = node.name == "ol"
    number = _list_start(node.get("start")) if ordered else 0
    lines: list[str] = []
    for item in node.find_all("li", recursive=False):
        nested = [child for child in item.children if isinstance(child, Tag) and child.name in {"ul", "ol"}]
        text = _collapse_lines(_render_inline([c for c in item.children if c not in nested], delimiters, in_table=False))
        marker = f"{number}." if ordered else "-"
        if text or nested:
            lines.append(f"{'    ' * depth}{marker} {text}".rstrip())
        for child in nested:
            lines.extend(_render_list(child, delimiters, depth + 1))
        number += 1
    return lines


def flatten_html_table(table: Tag, delimiters: LatexDelimitersConfig) -> str:
    """把任意 HTML table 拍平为矩形 GFM 表格；合并单元格只在首格保留内容。"""
    rows: list[list[str]] = []
    pending: dict[int, int] = {}
    for row in table.find_all("tr"):
        if row.find_parent("table") is not table:
            continue
        values: list[str] = []
        column = 0
        for cell in row.find_all(("th", "td"), recursive=False):
            while pending.get(column, 0):
                pending[column] -= 1
                values.append("")
                column += 1
            width = _span_count(cell.get("colspan"))
            height = _span_count(cell.get("rowspan"))
            values.append(_normalize_cell_text(_render_inline(cell.children, delimiters, in_table=True)))
            values.extend([""] * (width - 1))
            for position in range(column, column + width):
                pending[position] = height - 1
            column += width
        while any(remaining and position >= column for position, remaining in pending.items()):
            if pending.get(column, 0):
                pending[column] -= 1
            values.append("")
            column += 1
        rows.append(values)
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    if width == 0:
        return ""
    for row in rows:
        row.extend([""] * (width - len(row)))
    return "\n".join(
        [_format_markdown_row(rows[0]), _format_markdown_row(["---"] * width)] + [_format_markdown_row(row) for row in rows[1:]]
    )


def _render_inline(
    children: Iterable[PageElement],
    delimiters: LatexDelimitersConfig,
    *,
    in_table: bool,
    styles: tuple[str, ...] = (),
) -> str:
    """递归渲染行内 HTML；表格内块边界与换行降级为空格，列表项以分号连接。"""
    parts: list[str] = []
    for child in children:
        if isinstance(child, PreformattedString):
            # 注释、声明与处理指令不是可见文字。
            continue
        if isinstance(child, NavigableString):
            text = re.sub(r"\s+", " ", str(child))
            escaped = _escape_cell_text(text) if in_table else _escape_text(text)
            parts.append(render_styled_markdown_text(escaped, styles))
            continue
        if not isinstance(child, Tag) or child.name in _DROPPED_TAGS:
            continue
        name = child.name
        if name == "br":
            parts.append(" " if in_table else "\n")
        elif name == "img":
            parts.append(_render_image(child, in_table=in_table))
        elif name == "eq":
            parts.append(_render_formula(child.get_text().strip(), delimiters, in_table=in_table))
        elif name == "math":
            latex = str(child.get("alttext") or "").strip()
            if latex:
                parts.append(_render_formula(latex, delimiters, in_table=in_table))
            else:
                parts.append(_render_inline(child.children, delimiters, in_table=in_table, styles=styles))
        elif name == "code":
            content = re.sub(r"\s+", " ", child.get_text())
            parts.append(_render_inline_code(content) if in_table else _render_code_span(content))
        elif name == "a":
            label = _render_inline(child.children, delimiters, in_table=in_table, styles=styles)
            href = str(child.get("href", "")).strip()
            if not href or href.startswith("#") or not label.strip():
                parts.append(label)
            else:
                parts.append(f"[{_escape_link_label(label)}]({_escape_link_url(href)})")
        elif name in _STYLE_TAGS:
            nested_styles = tuple(dict.fromkeys((*styles, _STYLE_TAGS[name])))
            parts.append(_render_inline(child.children, delimiters, in_table=in_table, styles=nested_styles))
        elif name in {"ul", "ol"}:
            items = [
                _collapse_lines(_render_inline(item.children, delimiters, in_table=in_table, styles=styles))
                for item in child.find_all("li", recursive=False)
            ]
            parts.append(f" {'; '.join(item for item in items if item)} ")
        elif name in _BLOCK_TAGS or _HEADING_RE.fullmatch(name):
            separator = " " if in_table else "\n"
            parts.append(
                f"{separator}{_render_inline(child.children, delimiters, in_table=in_table, styles=styles)}{separator}"
            )
        else:
            parts.append(_render_inline(child.children, delimiters, in_table=in_table, styles=styles))
    return "".join(parts)


def _render_image(node: Tag, *, in_table: bool) -> str:
    """把 HTML 图片转为 Markdown 图片；无地址时保留替代文字。"""
    source = str(node.get("src", "")).strip()
    alt = re.sub(r"\s+", " ", str(node.get("alt", ""))).strip()
    escaped_alt = _escape_cell_text(alt) if in_table else _escape_text(alt)
    if not source:
        return escaped_alt
    return build_markdown_image(source, escaped_alt)


def _render_formula(latex: str, delimiters: LatexDelimitersConfig, *, in_table: bool) -> str:
    """使用配置的行内公式定界符输出 LaTeX，表格内转义竖线。"""
    if not latex:
        return ""
    if in_table:
        latex = _escape_gfm_formula_pipes(latex)
    return f" {delimiters.inline.left}{latex}{delimiters.inline.right} "


def _render_code_span(content: str) -> str:
    """选择长于内容反引号游程的 fence 输出行内代码。"""
    longest = max((len(match.group(0)) for match in re.finditer(r"`+", content)), default=0)
    fence = "`" * (longest + 1)
    padding = " " if content.startswith(("`", " ")) or content.endswith(("`", " ")) else ""
    return f"{fence}{padding}{content}{padding}{fence}"


def _fenced(content: str) -> str:
    """把预格式文本包装为围栏代码块。"""
    longest = max((len(match.group(0)) for match in re.finditer(r"`+", content)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}\n{content.strip(chr(10))}\n{fence}"


def _escape_text(content: str) -> str:
    """转义 HTML 起始字符与行内 Markdown 符号，避免文字被解析为标签或强调。"""
    return escape_conservative_markdown_text(content.replace("&", "&amp;").replace("<", "&lt;"))


def _escape_link_label(label: str) -> str:
    """转义链接标签中未转义的方括号。"""
    return re.sub(r"(?<!\\)([\[\]])", r"\\\1", label)


def _collapse_lines(content: str) -> str:
    """把多行行内结果压成单行。"""
    return re.sub(r"\s+", " ", content).strip()


def _span_count(value: object) -> int:
    """解析 colspan 或 rowspan，非法值回退 1 并限制上界。"""
    try:
        return min(_MAX_SPAN, max(1, int(str(value).strip())))
    except ValueError:
        return 1


def _list_start(value: object) -> int:
    """解析有序列表 start，非法值回退 1。"""
    try:
        return max(0, int(str(value).strip()))
    except ValueError:
        return 1


__all__ = ["flatten_html_table", "html_to_pure_markdown"]
