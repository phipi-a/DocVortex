"""Convert HTML-enhanced Markdown with an explicit source-range edit trace."""

from __future__ import annotations

import re
from bisect import bisect_right
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import quote


@dataclass(frozen=True)
class MarkdownEdit:
    """A replacement in the original Unicode string."""

    start: int
    end: int
    replacement: str
    coarse: bool = False


@dataclass(frozen=True)
class PureMarkdown:
    """Converted text and ordered edits for translating source ranges."""

    markdown: str
    edits: tuple[MarkdownEdit, ...]
    _ends: tuple[int, ...] = field(init=False, repr=False)
    _deltas: tuple[int, ...] = field(init=False, repr=False)
    _coarse_starts: tuple[int, ...] = field(init=False, repr=False)
    _coarse_ends: tuple[int, ...] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        delta = 0
        deltas = [0]
        for edit in self.edits:
            delta += len(edit.replacement) - (edit.end - edit.start)
            deltas.append(delta)
        object.__setattr__(self, "_ends", tuple(edit.end for edit in self.edits))
        object.__setattr__(self, "_deltas", tuple(deltas))
        object.__setattr__(self, "_coarse_starts", tuple(edit.start for edit in self.edits if edit.coarse))
        object.__setattr__(self, "_coarse_ends", tuple(edit.end for edit in self.edits if edit.coarse))

    def translate_range(self, start: int, end: int) -> tuple[int, int]:
        """Translate a source range, enclosing replacements at partial boundaries."""
        return self._boundary(start, False), self._boundary(end, True)

    def _boundary(self, offset: int, is_end: bool) -> int:
        index = bisect_right(self._ends, offset)
        delta = self._deltas[index]
        if index < len(self.edits):
            edit = self.edits[index]
            if edit.start < offset:
                return edit.start + delta + (len(edit.replacement) if is_end else 0)
        return offset + delta

    def coarsens_range(self, start: int, end: int) -> bool:
        """Report whether a structure replacement intersects a source range."""
        index = bisect_right(self._coarse_ends, start)
        return index < len(self._coarse_starts) and self._coarse_starts[index] < end


def _destination(value: str) -> str:
    return quote(value, safe="/:#?&=%@+~,;!$'*-._")


def _label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("[", r"\[").replace("]", r"\]")


def _fenced(content: str) -> str:
    runs = [len(match.group()) for match in re.finditer(r"`+", content)]
    fence = "`" * max(3, max(runs, default=0) + 1)
    return f"\n\n{fence}\n{content.strip(chr(10))}\n{fence}\n\n"


def _protected_source(markdown: str) -> str:
    """Mask fenced/inline code and math while retaining all source positions."""
    chars = list(markdown)
    fence: str | None = None
    offset = 0
    for line in markdown.splitlines(keepends=True):
        marker = re.match(r"^[ \t]{0,3}(`{3,}|~{3,})", line)
        if fence is None and marker and marker.group(1).startswith("`") and "`" in line[marker.end() :]:
            marker = None
        protected = fence is not None or marker is not None or line.startswith(("    ", "\t"))
        if fence is not None:
            if re.match(rf"^[ \t]{{0,3}}{re.escape(fence[0])}{{{len(fence)},}}[ \t]*$", line.rstrip("\r\n")):
                fence = None
        elif marker:
            fence = marker.group(1)
        if protected:
            chars[offset : offset + len(line)] = ["\n" if char == "\n" else " " for char in line]
        offset += len(line)
    masked = "".join(chars)
    pattern = (
        r"(?P<htmlcode><(?:code|pre)\b[^>]*>[\s\S]*?</(?:code|pre)>)"
        r"|(?<!\\)(?P<ticks>`+)(?!`)[\s\S]*?(?<!`)(?P=ticks)(?!`)|\\\([\s\S]*?\\\)|\\\[[\s\S]*?\\\]"
        r"|(?<!\\)\${1,2}[^$]*?(?<!\\)\${1,2}|<(?:[a-z][a-z0-9+.-]{1,31}:[^<>\s]*|[^<>\s@]+@[^<>\s@]+)>"
    )
    for match in re.finditer(pattern, masked, flags=re.IGNORECASE):
        if match.group("htmlcode"):
            continue
        chars[match.start() : match.end()] = ["\n" if char == "\n" else " " for char in match.group()]
    return "".join(chars)


def _table(markup: str) -> str:
    """Flatten merged/nested cells into a rectangular GFM table."""
    from bs4 import BeautifulSoup

    table = BeautifulSoup(markup, "html.parser").find("table")
    if table is None:
        return ""
    rows: list[list[str]] = []
    spans: dict[int, int] = {}
    for row in table.find_all("tr"):
        if row.find_parent("table") is not table:
            continue
        values: list[str] = []
        column = 0
        for cell in row.find_all(["th", "td"], recursive=False):
            while spans.get(column, 0):
                spans[column] -= 1
                values.append("")
                column += 1
            for nested in cell.find_all("table"):
                nested.replace_with(nested.get_text(" ", strip=True))
            content = convert_to_pure_markdown(cell.decode_contents()).markdown
            content = re.sub(r"\s*\n\s*", " ", content).strip()
            content = re.sub(r"(?<!\\)\|", r"\\|", content)
            width = _span_count(cell.get("colspan"))
            height = _span_count(cell.get("rowspan"))
            values.extend([content] + [""] * (width - 1))
            for position in range(column, column + width):
                spans[position] = height - 1
            column += width
        while column <= max(spans, default=-1):
            if spans.get(column, 0):
                spans[column] -= 1
            values.append("")
            column += 1
        rows.append(values)
    if not rows:
        return ""
    width = max(map(len, rows))
    lines = ["| " + " | ".join(row + [""] * (width - len(row))) + " |" for row in rows]
    lines.insert(1, "| " + " | ".join(["---"] * width) + " |")
    return "\n\n" + "\n".join(lines) + "\n\n"


def _span_count(value: object) -> int:
    try:
        return min(1000, max(1, int(str(value))))
    except ValueError:
        return 1


class _Converter(HTMLParser):
    def __init__(self, source: str):
        super().__init__(convert_charrefs=False)
        self.source = source
        self.lines = [0] + [match.end() for match in re.finditer("\n", source)]
        self.edits: list[MarkdownEdit] = []
        self.stack: list[tuple[str, str]] = []
        self.special: tuple[str, int, int] | None = None

    def _offset(self) -> int:
        line, column = self.getpos()
        return self.lines[line - 1] + column

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        start = self._offset()
        end = start + len(self.get_starttag_text())
        attributes = dict(attrs)
        if self.special is not None:
            name, origin, depth = self.special
            if tag == name:
                self.special = name, origin, depth + 1
            return
        if tag in {"table", "pre", "script", "style"} or (
            tag == "div" and "docvortex-algorithm" in (attributes.get("class") or "").split()
        ):
            self.special = tag, start, 1
            return
        wrappers = {"strong": "**", "b": "**", "em": "*", "i": "*", "s": "~~", "del": "~~", "strike": "~~"}
        replacement = wrappers.get(tag, "")
        closing = replacement
        if tag == "a":
            href = attributes.get("href") or ""
            replacement = "[" if href and not href.startswith("#") else ""
            closing = f"]({_destination(href)})" if replacement else ""
        elif tag == "img":
            src = attributes.get("src") or ""
            replacement = f"![{_label(attributes.get('alt') or '')}]({_destination(src)})" if src else ""
        elif tag == "code":
            # A coarse rewrite below chooses a safe delimiter for literal backticks.
            self.special = tag, start, 1
            return
        elif tag in {"br", "hr"}:
            replacement = "\n" if tag == "br" else "\n\n---\n\n"
            line_start = self.lines[self.getpos()[0] - 1]
            if tag == "br" and re.match(r"^[ \t]*\|", self.source[line_start:start]):
                replacement = " "
        elif tag == "li":
            replacement, closing = "\n- ", "\n"
        elif tag == "summary":
            replacement, closing = "\n\n**", "**\n\n"
        elif tag in {"p", "div", "details", "ul", "ol", "blockquote"}:
            replacement = closing = "\n\n"
        elif re.fullmatch(r"h[1-6]", tag):
            replacement, closing = "\n\n" + "#" * int(tag[1]) + " ", "\n\n"
        self.edits.append(MarkdownEdit(start, end, replacement))
        if tag not in {"img", "br", "hr", "input", "meta", "link", "wbr", "source", "area", "embed", "param", "col", "base"}:
            self.stack.append((tag, closing))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if self.stack and self.stack[-1][0] == tag:
            self.stack.pop()

    def handle_endtag(self, tag: str) -> None:
        start = self._offset()
        end = self.source.find(">", start) + 1
        if self.special is not None:
            name, origin, depth = self.special
            if tag != name:
                return
            if depth > 1:
                self.special = name, origin, depth - 1
                return
            self._special_edit(name, origin, end)
            self.special = None
            return
        replacement = ""
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                replacement = self.stack.pop(index)[1]
                break
        self.edits.append(MarkdownEdit(start, end, replacement))

    def _special_edit(self, tag: str, start: int, end: int) -> None:
        from bs4 import BeautifulSoup

        markup = self.source[start:end]
        if tag == "table":
            replacement = _table(markup)
        elif tag in {"script", "style"}:
            replacement = ""
        else:
            content = BeautifulSoup(markup, "html.parser").get_text()
            if tag == "code":
                fence = "`" * (max((len(m.group()) for m in re.finditer(r"`+", content)), default=0) + 1)
                padding = " " if content.startswith(("`", " ")) or content.endswith(("`", " ")) else ""
                replacement = f"{fence}{padding}{content}{padding}{fence}"
            else:
                replacement = _fenced(content)
        self.edits.append(MarkdownEdit(start, end, replacement, coarse=True))

    def handle_comment(self, data: str) -> None:
        if self.special is None:
            start = self._offset()
            end = self.source.find("-->", start)
            self.edits.append(MarkdownEdit(start, end + 3 if end >= 0 else len(self.source), ""))

    def handle_decl(self, decl: str) -> None:
        if self.special is None:
            start = self._offset()
            self.edits.append(MarkdownEdit(start, self.source.find(">", start) + 1, ""))

    def handle_pi(self, data: str) -> None:
        if self.special is None:
            start = self._offset()
            self.edits.append(MarkdownEdit(start, self.source.find(">", start) + 1, ""))


def convert_to_pure_markdown(markdown: str) -> PureMarkdown:
    """Remove raw HTML while preserving code/math and tracing Unicode replacements.

    Uses GFM tables and strikethrough. Unsupported visual styles are flattened;
    merged cells lose their spans. HTML anchors and HTML fragment links are removed.
    """
    parser = _Converter(markdown)
    parser.feed(_protected_source(markdown))
    parser.close()
    if parser.special is not None:
        tag, start, _ = parser.special
        parser._special_edit(tag, start, len(markdown))
    edits = tuple(sorted(parser.edits, key=lambda edit: edit.start))
    parts: list[str] = []
    cursor = 0
    for edit in edits:
        parts.extend((markdown[cursor : edit.start], edit.replacement))
        cursor = edit.end
    parts.append(markdown[cursor:])
    return PureMarkdown("".join(parts), edits)


__all__ = ["MarkdownEdit", "PureMarkdown", "convert_to_pure_markdown"]
