"""Middle JSON 2.0 行内 Span 到 Markdown 的安全序列化。

渲染以 InlinePiece 序列进行：每段输出记录产生它的 Span 路径，以及叶子 Span
content 中的字符区间（样式、分隔符和链接语法等包装符号没有字符区间）。
字符串输出只是这些片段的拼接，因此来源追踪与输出始终使用同一实现。
"""

from __future__ import annotations

import html
import re
from collections.abc import Sequence
from dataclasses import dataclass

from ....content.inline import join_inline_spans
from ....options import LatexDelimitersConfig
from ....schema import CodeInlineSpan, EquationInlineSpan, HyperlinkSpan, InlineSpan, TextSpan
from .dialect import is_pure_markdown
from .escaping import conservative_markdown_escapes

_HTML_LIKE_TEXT_RE = re.compile(r"</?[A-Za-z][^<>\n]*>|<!--.*?-->|<![A-Za-z][^<>\n]*>|<\?[^<>\n]*\?>")
_ENTITY_LIKE_RE = re.compile(r"&(?:#[xX][0-9A-Fa-f]+|#[0-9]+|[A-Za-z][A-Za-z0-9]+);?")
_LINK_LABEL_BRACKET_RE = re.compile(r"(?<!\\)([\[\]])")
_SIMPLE_STYLE_WRAPPERS = {
    frozenset({"bold"}): "**",
    frozenset({"italic"}): "*",
    frozenset({"strikethrough"}): "~~",
    frozenset({"bold", "italic"}): "***",
}
_EMPHASIS_STYLES = frozenset({"bold", "italic"})


@dataclass(frozen=True, slots=True)
class InlinePiece:
    """一段非空输出；source 为叶子 Span content 的字符区间，包装符号为 None。"""

    text: str
    path: tuple[int, ...]
    source: tuple[int, int] | None = None


def render_inline_content(content: list[InlineSpan], delimiters: LatexDelimitersConfig) -> str:
    """把一段 MiddleJson 行内内容渲染为 Markdown。"""
    return render_inline_spans(content, delimiters)


def trace_inline_content(content: list[InlineSpan], delimiters: LatexDelimitersConfig) -> list[InlinePiece]:
    """渲染行内内容并保留每段输出的来源；路径以 content 下标开始，链接子节点追加子下标。"""
    return [piece for index, span in enumerate(content) for piece in _render_inline_span(span, delimiters, (index,))]


def render_joined_inline_contents(contents: list[list[InlineSpan]], delimiters: LatexDelimitersConfig) -> str:
    """按物理段落边界规则合并多段 content 后渲染 Markdown。"""
    return render_inline_spans(join_inline_spans(contents), delimiters)


def render_inline_spans(spans: list[InlineSpan], delimiters: LatexDelimitersConfig) -> str:
    """把行内 Span 序列化为 Markdown 与必要的安全 HTML。"""
    return _joined(trace_inline_content(spans, delimiters))


def render_inline_spans_in_html_context(spans: list[InlineSpan], delimiters: LatexDelimitersConfig) -> str:
    """把 Markdown raw HTML 容器内的 Span 全部序列化为安全 HTML 行内语法。"""
    return _joined(
        [piece for index, span in enumerate(spans) for piece in _render_inline_span_in_html_context(span, delimiters, (index,))]
    )


def _joined(pieces: Sequence[InlinePiece]) -> str:
    """拼接片段得到最终输出。"""
    return "".join(piece.text for piece in pieces)


def _wrapper(text: str, path: tuple[int, ...]) -> list[InlinePiece]:
    """包装符号片段，空串不产生片段。"""
    return [InlinePiece(text, path)] if text else []


def _characters(content: str, path: tuple[int, ...], emit: Sequence[str] | None = None) -> list[InlinePiece]:
    """逐字符片段；emit 给出每个源字符的输出，缺省为原字符。"""
    texts = content if emit is None else emit
    return [InlinePiece(text, path, (index, index + 1)) for index, text in enumerate(texts) if text]


def _untraced(content: str) -> list[InlinePiece]:
    """把已渲染的字符串转为逐字符片段，供无来源的字符串接口复用片段规则。"""
    return [InlinePiece(char, ()) for char in content]


def _render_inline_span(span: InlineSpan, delimiters: LatexDelimitersConfig, path: tuple[int, ...]) -> list[InlinePiece]:
    """渲染单个结构化行内 Span。"""
    if isinstance(span, TextSpan):
        content = _escape_plain_markdown_text(span.content, path)
        return _apply_styles(content, span.content, span.styles, path)
    if isinstance(span, CodeInlineSpan):
        return _render_inline_code(span.content, path)
    if isinstance(span, EquationInlineSpan):
        return [
            *_wrapper(delimiters.inline.left, path),
            *_characters(span.content, path),
            *_wrapper(delimiters.inline.right, path),
        ]
    if isinstance(span, HyperlinkSpan):
        label = [
            piece
            for index, child in enumerate(span.content)
            for piece in _render_inline_span(child, delimiters, (*path, index))
        ]
        use_html = not is_pure_markdown() and _requires_html_link(list(span.content))
        return _render_link(label, span.url, use_html, path)
    raise TypeError(f"Unsupported inline span: {type(span).__name__}")


def _render_inline_span_in_html_context(
    span: InlineSpan, delimiters: LatexDelimitersConfig, path: tuple[int, ...]
) -> list[InlinePiece]:
    """渲染一个嵌入 Markdown raw HTML block 的结构化行内 Span。"""
    if isinstance(span, TextSpan):
        return _apply_html_styles(_html_escaped(span.content, path), span.styles, path)
    if isinstance(span, CodeInlineSpan):
        return [*_wrapper("<code>", path), *_html_escaped(span.content, path), *_wrapper("</code>", path)]
    if isinstance(span, EquationInlineSpan):
        return [
            *_wrapper(html.escape(delimiters.inline.left, quote=False), path),
            *_html_escaped(span.content, path),
            *_wrapper(html.escape(delimiters.inline.right, quote=False), path),
        ]
    if isinstance(span, HyperlinkSpan):
        label = [
            piece
            for index, child in enumerate(span.content)
            for piece in _render_inline_span_in_html_context(child, delimiters, (*path, index))
        ]
        return _render_link(label, span.url, True, path)
    raise TypeError(f"Unsupported inline span: {type(span).__name__}")


def _html_escaped(content: str, path: tuple[int, ...]) -> list[InlinePiece]:
    """逐字符 HTML 转义。"""
    return _characters(content, path, [html.escape(char, quote=False) for char in content])


def _render_inline_code(content: str, path: tuple[int, ...]) -> list[InlinePiece]:
    """选择长于内容中反引号游程的 fence，稳定输出 Markdown 行内代码。"""
    normalized: list[InlinePiece] = []
    index = 0
    while index < len(content):
        width = 2 if content.startswith("\r\n", index) else 1
        char = content[index]
        normalized.append(InlinePiece(" " if char in "\r\n" else char, path, (index, index + width)))
        index += width
    text = _joined(normalized)
    longest = max((len(match.group(0)) for match in re.finditer(r"`+", text)), default=0)
    fence = "`" * (longest + 1)
    if text.startswith(("`", " ")) or text.endswith(("`", " ")):
        return [*_wrapper(f"{fence} ", path), *normalized, *_wrapper(f" {fence}", path)]
    return [*_wrapper(fence, path), *normalized, *_wrapper(fence, path)]


def _escape_plain_markdown_text(content: str, path: tuple[int, ...]) -> list[InlinePiece]:
    """转义 Markdown 符号，并把普通文字中的标签外观保持为惰性实体。"""
    parts: list[InlinePiece] = []
    cursor = 0
    for match in _HTML_LIKE_TEXT_RE.finditer(content):
        parts.extend(_escape_entity_like_text(_escape_conservative_range(content, cursor, match.start(), path)))
        parts.extend(_shifted(_html_escaped(match.group(0), path), match.start()))
        cursor = match.end()
    parts.extend(_escape_entity_like_text(_escape_conservative_range(content, cursor, len(content), path)))
    return parts


def _shifted(pieces: list[InlinePiece], offset: int) -> list[InlinePiece]:
    """把局部字符区间平移到所属 Span content 的坐标。"""
    return [
        InlinePiece(
            piece.text, piece.path, None if piece.source is None else (piece.source[0] + offset, piece.source[1] + offset)
        )
        for piece in pieces
    ]


def _escape_conservative_range(content: str, start: int, end: int, path: tuple[int, ...]) -> list[InlinePiece]:
    """对 content[start:end] 独立执行保守转义。"""
    segment = content[start:end]
    return _shifted(_characters(segment, path, conservative_markdown_escapes(segment)), start)


def _escape_entity_like_text(pieces: list[InlinePiece]) -> list[InlinePiece]:
    """保护会被下游 Markdown 解析器当作 HTML 实体的字面量文本。"""
    text = _joined(pieces)
    protected = {match.start() for match in _ENTITY_LIKE_RE.finditer(text) if html.unescape(match.group(0)) != match.group(0)}
    if not protected:
        return pieces
    result = []
    offset = 0
    for piece in pieces:
        # 保守转义从不改写 "&"，候选起点必然是一个单字符片段。
        result.append(InlinePiece("&amp;", piece.path, piece.source) if offset in protected else piece)
        offset += len(piece.text)
    return result


def _apply_styles(
    content: list[InlinePiece], plain_text: str, styles: Sequence[str], path: tuple[int, ...]
) -> list[InlinePiece]:
    """按样式复杂度选择 Markdown wrapper 或安全 HTML 标签。"""
    if not content or not styles:
        return content
    marker = _get_visible_space_marker(styles)
    if marker is not None:
        rendered_markers = _render_visible_space_marker_text(content, plain_text, styles, marker, path)
        if rendered_markers is not None:
            return rendered_markers
    if plain_text and not plain_text.strip() and any(style in styles for style in ("underline", "strikethrough", "emphasis")):
        return _render_visible_whitespace(plain_text, styles, path)

    return _apply_style_wrappers(content, styles, path)


def _get_visible_space_marker(styles: Sequence[str]) -> str | None:
    """按 dev 规则选择可见空格 marker，下划线优先于删除线。"""
    if "underline" in styles:
        return "_"
    if "strikethrough" in styles:
        return "-"
    return None


def _render_visible_space_marker_text(
    content: list[InlinePiece],
    plain_text: str,
    styles: Sequence[str],
    marker: str,
    path: tuple[int, ...],
) -> list[InlinePiece] | None:
    """把纯 ASCII 空格或非空文本首尾空格转换为可见 marker。"""
    if not plain_text:
        return None
    style_key = frozenset(styles)
    force_html = style_key not in _SIMPLE_STYLE_WRAPPERS
    if all(char == " " for char in plain_text):
        ignored_style = "underline" if marker == "_" else "strikethrough"
        remaining_styles = [style for style in styles if style != ignored_style]
        return _apply_style_wrappers(
            _characters(plain_text, path, [marker] * len(plain_text)),
            remaining_styles,
            path,
            force_html=force_html,
        )

    leading_count = len(plain_text) - len(plain_text.lstrip(" "))
    trailing_count = len(plain_text) - len(plain_text.rstrip(" "))
    if leading_count == 0 and trailing_count == 0:
        return None
    text = _joined(content)
    if not text.startswith(" " * leading_count) or not text.endswith(" " * trailing_count):
        return None
    # 空格不被转义，首尾空格各自对应一个单字符片段。
    content_end = len(content) - trailing_count
    rendered = [
        *(InlinePiece(marker, piece.path, piece.source) for piece in content[:leading_count]),
        *content[leading_count:content_end],
        *(InlinePiece(marker, piece.path, piece.source) for piece in content[content_end:]),
    ]
    return _apply_style_wrappers(rendered, styles, path, force_html=force_html)


def _split(pieces: list[InlinePiece], offset: int) -> tuple[list[InlinePiece], list[InlinePiece]]:
    """在输出偏移处切分；包装符号可任意切分，源字符片段只能在其边界切分。"""
    cursor = 0
    for index, piece in enumerate(pieces):
        if cursor == offset:
            return pieces[:index], pieces[index:]
        end = cursor + len(piece.text)
        if offset < end:
            if piece.source is not None:
                raise ValueError("cannot split the emission of one source character")
            left = InlinePiece(piece.text[: offset - cursor], piece.path)
            right = InlinePiece(piece.text[offset - cursor :], piece.path)
            return [*pieces[:index], left], [right, *pieces[index + 1 :]]
        cursor = end
    return pieces, []


def _apply_style_wrappers(
    content: list[InlinePiece],
    styles: Sequence[str],
    path: tuple[int, ...],
    *,
    force_html: bool = False,
) -> list[InlinePiece]:
    """给已处理空格的内容添加 Markdown 或 HTML 样式 wrapper。"""
    if not content or not styles:
        return content

    text = _joined(content)
    core_text = text.strip(" \t")
    if not core_text:
        return content
    leading, rest = _split(content, len(text) - len(text.lstrip(" \t")))
    core, trailing = _split(rest, len(core_text))

    if is_pure_markdown():
        return [*leading, *_wrap_pure_markdown_styles(core, styles, path), *trailing]
    style_key = frozenset(styles)
    wrapper = _SIMPLE_STYLE_WRAPPERS.get(style_key)
    if wrapper is not None and not force_html:
        return [*leading, *_wrapper(wrapper, path), *core, *_wrapper(wrapper, path), *trailing]
    return [*leading, *_apply_html_styles(core, styles, path), *trailing]


def _wrap_pure_markdown_styles(content: list[InlinePiece], styles: Sequence[str], path: tuple[int, ...]) -> list[InlinePiece]:
    """只保留 GFM 可表达的粗体、斜体与删除线；上下标用 ^ / _ 前缀标记，其余视觉样式退化为纯文字。"""
    if "superscript" in styles:
        content = [*_wrapper("^", path), *content]
    elif "subscript" in styles:
        content = [*_wrapper("\\_", path), *content]
    wrapper = _SIMPLE_STYLE_WRAPPERS.get(frozenset(styles) & _EMPHASIS_STYLES, "")
    content = [*_wrapper(wrapper, path), *content, *_wrapper(wrapper, path)]
    if "strikethrough" in styles:
        content = [*_wrapper("~~", path), *content, *_wrapper("~~", path)]
    return content


def render_styled_markdown_text(content: str, styles: Sequence[str]) -> str:
    """按正文相同规则把已转义文字渲染为 Markdown 或安全 HTML 样式。"""
    return _joined(_apply_style_wrappers(_untraced(content), styles, ()))


def markdown_styles_require_html(styles: Sequence[str]) -> bool:
    """判断样式组合是否必须整体使用 HTML 标签表达。"""
    return bool(styles) and frozenset(styles) not in _SIMPLE_STYLE_WRAPPERS


def _expanded_tabs(content: str) -> list[str]:
    """逐字符给出 str.expandtabs(4) 的输出。"""
    expanded = []
    column = 0
    for char in content:
        if char == "\t":
            width = 4 - column % 4
            expanded.append(" " * width)
            column += width
        else:
            expanded.append(char)
            column = 0 if char in "\r\n" else column + 1
    return expanded


def _render_visible_whitespace(content: str, styles: Sequence[str], path: tuple[int, ...]) -> list[InlinePiece]:
    """使用原 HTML 规则保留非 ASCII marker 场景的可见空白；纯 Markdown 改用 marker 字符。"""
    expanded = _expanded_tabs(content)
    if is_pure_markdown():
        marker = _get_visible_space_marker(styles)
        if marker is None:
            return _characters(content, path)
        return _characters(content, path, ["".join(c if c == "\n" else marker for c in text) for text in expanded])
    visible = ["".join("<br>" if c == "\n" else "&nbsp;" for c in text) for text in expanded]
    return _apply_html_styles(_characters(content, path, visible), styles, path)


def _apply_html_styles(content: list[InlinePiece], styles: Sequence[str], path: tuple[int, ...]) -> list[InlinePiece]:
    """按稳定顺序给复杂样式添加 HTML wrapper。"""

    def wrap(opening: str, closing: str) -> None:
        nonlocal content
        content = [*_wrapper(opening, path), *content, *_wrapper(closing, path)]

    if "superscript" in styles:
        wrap("<sup>", "</sup>")
    elif "subscript" in styles:
        wrap("<sub>", "</sub>")
    if "underline" in styles:
        wrap("<u>", "</u>")
    if "bold" in styles:
        wrap("<strong>", "</strong>")
    if "italic" in styles:
        wrap("<em>", "</em>")
    if "strikethrough" in styles:
        wrap("<s>", "</s>")
    if "emphasis" in styles:
        wrap('<span style="text-emphasis: dot; text-emphasis-position: under;">', "</span>")
    return content


def _requires_html_link(spans: list[InlineSpan]) -> bool:
    """判断链接标签是否含不适合嵌入 Markdown link 的复杂样式。"""
    for span in spans:
        if isinstance(span, TextSpan):
            if span.styles and frozenset(span.styles) not in _SIMPLE_STYLE_WRAPPERS:
                return True
    return False


def _render_link(label: list[InlinePiece], url: str, use_html: bool, path: tuple[int, ...]) -> list[InlinePiece]:
    """按标签复杂度输出 Markdown 或 HTML 超链接。"""
    if not label:
        return []
    if not url or url == ".":
        return label
    if is_pure_markdown() and url.startswith("#"):
        # 纯 Markdown 不输出 HTML anchor，文档内书签链接无法解析。
        return label
    if use_html:
        return [*_wrapper(f'<a href="{html.escape(url, quote=True)}">', path), *label, *_wrapper("</a>", path)]
    safe_url = url.replace("\\", "%5C").replace(" ", "%20").replace("(", "%28").replace(")", "%29")
    return [*_wrapper("[", path), *_escape_markdown_link_label(label), *_wrapper(f"]({safe_url})", path)]


def render_internal_link(label: str, anchor: str) -> str:
    """把已渲染目录标签包装为当前文档内锚点链接。"""
    safe_anchor = anchor.replace(" ", "%20").replace("(", "%28").replace(")", "%29")
    return f"[{_joined(_escape_markdown_link_label(_untraced(label)))}](#{safe_anchor})"


def _escape_markdown_link_label(label: list[InlinePiece]) -> list[InlinePiece]:
    """转义 Markdown link 标签中的方括号并保留既有反斜杠。"""
    text = _joined(label)
    result: list[InlinePiece] = []
    rest = label
    consumed = 0
    for match in _LINK_LABEL_BRACKET_RE.finditer(text):
        before, rest = _split(rest, match.start() - consumed)
        (bracket,), rest = _split(rest, 1)
        consumed = match.start() + 1
        result.extend(before)
        # 反斜杠归属被转义的源字符；包装符号中的方括号得到一个包装反斜杠。
        if bracket.source is not None:
            result.append(InlinePiece(f"\\{bracket.text}", bracket.path, bracket.source))
        else:
            result.extend([InlinePiece("\\", bracket.path), bracket])
    result.extend(rest)
    return result


__all__ = [
    "InlinePiece",
    "markdown_styles_require_html",
    "render_inline_content",
    "render_inline_spans",
    "render_inline_spans_in_html_context",
    "render_internal_link",
    "render_joined_inline_contents",
    "render_styled_markdown_text",
    "trace_inline_content",
]
