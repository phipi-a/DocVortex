"""Renderer-native HTML-free Markdown regressions."""

from __future__ import annotations

import re

import pytest
from _span_test_utils import inline as _inline

from docvortex.options import LatexDelimitersConfig
from docvortex.render import MarkdownRenderOptions, RenderFormat, render, render_markdown
from docvortex.render.fragments import render_inline_content
from docvortex.render.markdown import render_single_block
from docvortex.schema import (
    AlgorithmBodyBlock,
    ChartBlock,
    ChartBodyBlock,
    CodeBlock,
    ImageBlock,
    ImageBodyBlock,
    IndexBlock,
    ListBlock,
    MiddleJson,
    PageBlock,
    PageFootnoteBlock,
    PageInfo,
    ParagraphTitleBlock,
    Producer,
    TableBlock,
    TableBodyBlock,
    TextBlock,
)

markdown_it = pytest.importorskip("markdown_it")

_COMPLEX_TABLE = (
    "<table><thead><tr><th colspan='2'>Head <b>x</b></th><th>C</th></tr>"
    "<tr><th>A</th><th>B</th><th>C2</th></tr></thead>"
    "<tr><td rowspan='2'><ul><li>one</li><li>two</li></ul></td><td>a|b<br>c</td>"
    "<td><img src='images/t.png' alt='pic'><!-- hidden --><script>alert(1)</script></td></tr>"
    "<tr><td><a href='https://example.org/x'><u>link</u></a> <a href='#local'>local</a></td>"
    "<td><table><tr><td>in</td><td>ner</td></tr></table><eq>a|b</eq></td></tr></table>"
)


def _middle(*blocks: PageBlock) -> MiddleJson:
    """构造单页严格 MiddleJson。"""
    return MiddleJson(
        pages=[PageInfo(page_idx=0, blocks=list(blocks))],
        is_full_document=True,
        metadata={"file_suffix": "docx", "producer": Producer(name="docvortex", version="test")},
        extensions={},
    )


def _kitchen_sink() -> list[PageBlock]:
    """覆盖默认模式下所有输出 raw HTML 的 block 与样式。"""
    styled = [
        {"type": "text", "content": "Plain <div>literal</div> "},
        {"type": "text", "content": "under", "styles": ["underline"]},
        {"type": "text", "content": " "},
        {"type": "text", "content": "sup", "styles": ["superscript"]},
        {"type": "text", "content": " "},
        {"type": "text", "content": "boldstrike", "styles": ["bold", "strikethrough"]},
        {"type": "text", "content": " "},
        {"type": "text", "content": "bolditalicunder", "styles": ["bold", "italic", "underline"]},
        {"type": "text", "content": " "},
        {"type": "text", "content": "dots", "styles": ["emphasis"]},
        {"type": "text", "content": " gap "},
        {"type": "text", "content": "\t\t", "styles": ["underline"]},
        {"type": "text", "content": " "},
        {
            "type": "hyperlink",
            "url": "https://example.org/a",
            "content": [{"type": "text", "content": "styledlink", "styles": ["underline"]}],
        },
        {"type": "text", "content": " "},
        {"type": "hyperlink", "url": "#sec", "content": [{"type": "text", "content": "bookmark"}]},
    ]
    return [
        IndexBlock(
            type="index",
            index=0,
            content=[ParagraphTitleBlock(type="paragraph_title", level=2, anchor="sec", content=_inline("Section"))],
        ),
        ParagraphTitleBlock(type="paragraph_title", index=1, level=2, anchor="sec", content=_inline("Section")),
        TextBlock(type="text", index=2, anchor="para", content=styled),
        ListBlock(
            type="list",
            index=3,
            content=[
                TextBlock(type="text", content=_inline("1. first")),
                TextBlock(type="text", content=_inline("2. second")),
            ],
        ),
        TableBlock(type="table", index=4, content=[TableBodyBlock(type="table_body", index=4, content=_COMPLEX_TABLE)]),
        TableBlock(
            type="table",
            index=5,
            content=[
                TableBodyBlock(
                    type="table_body",
                    index=5,
                    content="<table><tr><th>K</th><th>V</th></tr><tr><td>x<br>y</td><td><a href='https://e.org'><u>u</u></a></td></tr></table>",
                )
            ],
        ),
        ImageBlock(
            type="image",
            index=6,
            sub_type="figure",
            content=[
                ImageBodyBlock(
                    type="image_body",
                    index=6,
                    image_path="images/f.png",
                    content="<p>Recognized <sup>2</sup></p><table><tr><td>r</td></tr></table><ol start='3'><li>item</li></ol>",
                )
            ],
        ),
        ChartBlock(
            type="chart",
            index=7,
            content=[
                ChartBodyBlock(
                    type="chart_body",
                    index=7,
                    image_path="images/c.png",
                    content="<table><tr><th>Year</th></tr><tr><td>2026</td></tr></table>",
                )
            ],
        ),
        CodeBlock(
            type="code",
            index=8,
            sub_type="algorithm",
            content=[
                AlgorithmBodyBlock(
                    type="algorithm_body",
                    index=8,
                    content=[
                        {"type": "text", "content": "if a < b:\n    "},
                        {"type": "text", "content": "run", "styles": ["bold"]},
                        {"type": "text", "content": "()"},
                        {"type": "equation_inline", "content": "x^2"},
                    ],
                )
            ],
        ),
        PageFootnoteBlock(type="page_footnote", index=9, anchor="note", content=_inline("foot\nnote")),
    ]


def _html_tokens(markdown: str) -> list[str]:
    """用 CommonMark + GFM 表格/删除线解析，返回所有 raw HTML token 内容。"""
    parser = markdown_it.MarkdownIt("commonmark").enable(["table", "strikethrough"])
    found: list[str] = []
    stack = parser.parse(markdown)
    while stack:
        token = stack.pop()
        if token.type in {"html_block", "html_inline"}:
            found.append(token.content)
        stack.extend(token.children or [])
    return found


def test_default_kitchen_sink_contains_html() -> None:
    """确认测试文档确实覆盖默认模式的 HTML 输出路径。"""
    assert _html_tokens(render_markdown(_middle(*_kitchen_sink())))


def test_pure_output_has_no_raw_html() -> None:
    rendered = render_markdown(_middle(*_kitchen_sink()), pure_markdown=True)
    assert _html_tokens(rendered) == []
    assert "alert" not in rendered
    assert "hidden" not in rendered


def test_pure_output_keeps_visible_words() -> None:
    rendered = render_markdown(_middle(*_kitchen_sink()), pure_markdown=True)
    visible = re.sub(r"\\(.)", r"\1", rendered)
    for word in (
        "Plain", "literal", "under", "sup", "boldstrike", "bolditalicunder", "dots", "styledlink", "bookmark",
        "first", "second", "Head", "one", "two", "pic", "link", "local", "in", "ner", "Recognized", "item",
        "Year", "2026", "run", "foot", "note",
    ):  # fmt: skip
        assert word in visible, word


def test_pure_inline_styles() -> None:
    rendered = render_markdown(_middle(_kitchen_sink()[2]), pure_markdown=True)
    assert rendered == (
        "Plain &lt;div&gt;literal&lt;/div&gt; under ^sup ~~**boldstrike**~~ ***bolditalicunder*** dots gap "
        "________ [styledlink](https://example.org/a) bookmark"
    )


def test_pure_scripts_use_prefix_markers() -> None:
    spans = [
        {"type": "text", "content": "H"},
        {"type": "text", "content": "2", "styles": ["subscript"]},
        {"type": "text", "content": "O 10"},
        {"type": "text", "content": "-3", "styles": ["superscript"]},
    ]
    assert render_markdown(_middle(TextBlock(type="text", index=0, content=spans)), pure_markdown=True) == "H\\_2O 10^-3"


def test_pure_titles_index_and_footnote_drop_anchors() -> None:
    blocks = _kitchen_sink()
    rendered = render_markdown(_middle(blocks[0], blocks[1], blocks[9]), pure_markdown=True)
    assert rendered == "- Section\n\n## Section\n\nfoot\nnote"


def test_pure_complex_table_is_flattened() -> None:
    rendered = render_markdown(_middle(_kitchen_sink()[4]), pure_markdown=True)
    assert rendered == (
        "| Head **x** |  | C |\n"
        "| --- | --- | --- |\n"
        "| A | B | C2 |\n"
        "| one; two | a\\|b c | ![pic](images/t.png) |\n"
        "|  | [link](https://example.org/x) local | in ner $a\\|b$ |"
    )


def test_pure_simple_table_cells() -> None:
    rendered = render_markdown(_middle(_kitchen_sink()[5]), pure_markdown=True)
    assert rendered == "| K | V |\n| --- | --- |\n| x y | [u](https://e.org) |"


def test_pure_visual_details_are_expanded() -> None:
    blocks = _kitchen_sink()
    assert render_markdown(_middle(blocks[6]), pure_markdown=True) == (
        "![](images/f.png)\n\n**figure**\n\nRecognized ^2\n\n| r |\n| --- |\n\n3. item"
    )
    assert render_markdown(_middle(blocks[7]), pure_markdown=True) == (
        "![](images/c.png)\n\n**chart content**\n\n| Year |\n| --- |\n| 2026 |"
    )


def test_pure_algorithm_is_fenced_plain_text() -> None:
    rendered = render_markdown(_middle(_kitchen_sink()[8]), pure_markdown=True)
    assert rendered == "```\nif a < b:\n    run()$x^2$\n```"


def test_pure_blocks_compose_into_document() -> None:
    """逐块渲染再拼接必须等于整篇输出，供下游 markdown map 定位。"""
    blocks = _kitchen_sink()
    whole = render_markdown(_middle(*blocks), pure_markdown=True)
    parts = [render_markdown(_middle(block), pure_markdown=True) for block in blocks]
    assert "\n\n".join(part for part in parts if part) == whole


def test_pure_public_fragment_entry_points() -> None:
    delimiters = LatexDelimitersConfig()
    spans = TextBlock(type="text", content=[{"type": "text", "content": "x", "styles": ["underline", "bold"]}]).content
    assert render_inline_content(spans, delimiters) == "<strong><u>x</u></strong>"
    assert render_inline_content(spans, delimiters, pure_markdown=True) == "**x**"
    title = _kitchen_sink()[1]
    assert render_single_block(title, delimiters=delimiters, asset_base_url="").startswith("<a id=")
    assert render_single_block(title, delimiters=delimiters, asset_base_url="", pure_markdown=True) == "## Section"
    with pytest.raises(TypeError, match="pure_markdown"):
        render_markdown(_middle(title), pure_markdown="yes")  # type: ignore[arg-type]
    assert render(_middle(title), RenderFormat.MARKDOWN, options=MarkdownRenderOptions(pure_markdown=True)) == "## Section"
    with pytest.raises(TypeError, match="pure_markdown"):
        MarkdownRenderOptions(pure_markdown="yes")  # type: ignore[arg-type]
