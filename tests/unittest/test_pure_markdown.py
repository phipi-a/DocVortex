"""HTML-free rendering and source trace regressions."""

from __future__ import annotations

import re

import pytest

from docvortex.render import MarkdownRenderOptions, RenderFormat, render, render_markdown
from docvortex.render.pure_markdown import convert_to_pure_markdown
from docvortex.schema import MiddleJson


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("A<sup>1</sup> <sub>x</sub> <u>under</u>", "A1 x under"),
        ("<strong>bold</strong> <em>italic</em> <s>gone</s>", "**bold** *italic* ~~gone~~"),
        ('<a id="target"></a>Hello <a href="https://example.org/a(b)">link</a>', "Hello [link](https://example.org/a%28b%29)"),
        ('<img src="images/a (1).png" alt="a[b]">', r"![a\[b\]](images/a%20%281%29.png)"),
        ('<small><span style="color:gray">foot<br>note</span></small>', "foot\nnote"),
        ("<details>\n<summary>More</summary>\n\nbody\n</details>", "\n\n\n\n\n**More**\n\n\n\nbody\n\n\n"),
        ("before<!--hidden-->after<script>alert(1)</script>", "beforeafter"),
        ("`<u>literal</u>` and <u>text</u>", "`<u>literal</u>` and text"),
        ("```html\n<div>literal</div>\n```\n<u>text</u>", "```html\n<div>literal</div>\n```\ntext"),
        ("~~~\n<div>literal</div>\n~~~\n<u>text</u>", "~~~\n<div>literal</div>\n~~~\ntext"),
        (r"\(x < y\) <sup>2</sup>", r"\(x < y\) 2"),
        ("<https://example.org> <a@b.com>", "<https://example.org> <a@b.com>"),
        ("<code>a`b</code>", "``a`b``"),
        ("<code>`</code> <u>text</u> `later`", "`` ` `` text `later`"),
        ("```<u>literal</u>```\n<u>text</u>", "```<u>literal</u>```\ntext"),
        ("    <div>code</div>\n\n<u>text</u>", "    <div>code</div>\n\ntext"),
        (r"Cost \$5 <u>fee</u> \$10", r"Cost \$5 fee \$10"),
        (r"\`literal <u>text</u> \`", r"\`literal text \`"),
        ("| A | B |\n| --- | --- |\n| a<br>b | c |", "| A | B |\n| --- | --- |\n| a b | c |"),
    ],
)
def test_conversion(source: str, expected: str) -> None:
    assert convert_to_pure_markdown(source).markdown == expected


def test_table_flattens_spans_and_preserves_images() -> None:
    source = (
        '<table><tr><th colspan="2">Title</th></tr>'
        '<tr><td rowspan="2"><strong>A</strong></td><td><img src="images/a.png"></td></tr>'
        "<tr><td>B<br>C | D</td></tr></table>"
    )
    converted = convert_to_pure_markdown(source)
    assert converted.markdown.strip() == ("| Title |  |\n| --- | --- |\n| **A** | ![](images/a.png) |\n|  | B C \\| D |")
    assert converted.edits[0].coarse
    assert converted.translate_range(10, 15) == (0, len(converted.markdown))


def test_algorithm_is_a_code_fence() -> None:
    converted = convert_to_pure_markdown('<div class="docvortex-algorithm">if &lt;x&gt;:\n  <strong>run</strong>()</div>')
    assert converted.markdown.strip() == "```\nif <x>:\n  run()\n```"


def test_trace_keeps_unicode_offsets() -> None:
    source = "😀 <sup>1</sup> café"
    converted = convert_to_pure_markdown(source)
    assert converted.markdown == "😀 1 café"
    start = source.index("café")
    left, right = converted.translate_range(start, start + 4)
    assert converted.markdown[left:right] == "café"
    left, right = converted.translate_range(2, start - 1)
    assert converted.markdown[left:right] == "1"


def test_public_render_options() -> None:
    middle = MiddleJson.from_dict(
        {
            "schema": "docvortex.middle",
            "schema_version": "2.0",
            "is_full_document": True,
            "metadata": {"file_suffix": "docx", "producer": {"name": "docvortex", "version": "test"}},
            "extensions": {},
            "pages": [
                {
                    "page_idx": 0,
                    "blocks": [
                        {"type": "text", "index": 0, "content": [{"type": "text", "content": "Under", "styles": ["underline"]}]}
                    ],
                }
            ],
        }
    )
    assert "<u>" in render_markdown(middle)
    assert render_markdown(middle, pure_markdown=True) == "Under"
    assert render(middle, RenderFormat.MARKDOWN, options=MarkdownRenderOptions(pure_markdown=True)) == "Under"
    with pytest.raises(TypeError, match="pure_markdown"):
        MarkdownRenderOptions(pure_markdown="yes")


def test_every_emitted_style_is_html_free() -> None:
    source = '<span style="text-emphasis:dot"><em><strong><u><sup>x</sup></u></strong></em></span>'
    assert not re.search(r"</?[A-Za-z]", convert_to_pure_markdown(source).markdown)
