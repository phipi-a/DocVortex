"""Source traces of shared inline Markdown emissions."""

from __future__ import annotations

import pytest

from docvortex.options import LatexDelimitersConfig
from docvortex.render.fragments import InlineEmission, render_inline_content, trace_inline_content
from docvortex.schema import CodeInlineSpan, EquationInlineSpan, HyperlinkSpan, TextSpan

DELIMITERS = LatexDelimitersConfig()


def _text(content: str, *styles: str) -> TextSpan:
    return TextSpan(type="text", content=content, styles=list(styles))


@pytest.mark.parametrize("pure", [False, True])
def test_trace_matches_rendering_and_tiles_output(pure: bool) -> None:
    content = [
        _text("see "),
        _text("a_b", "bold"),
        _text(" & <i> "),
        EquationInlineSpan(type="equation_inline", content="x^2"),
        CodeInlineSpan(type="code_inline", content="a\r\nb"),
        HyperlinkSpan(type="hyperlink", url="https://example.com/(x)", content=[_text("[1]")]),
    ]
    traced = trace_inline_content(content, DELIMITERS, pure_markdown=pure)

    assert traced.markdown == render_inline_content(content, DELIMITERS, pure_markdown=pure)
    cursor = 0
    for emission in traced.emissions:
        assert emission.start == cursor < emission.end
        cursor = emission.end
    assert cursor == len(traced.markdown)


def test_link_label_words_map_inside_link_syntax() -> None:
    url = "https://github.com/microsoft/LoRA"
    content = [_text("at "), HyperlinkSpan(type="hyperlink", url=url, content=[_text(url)]), _text(".")]
    traced = trace_inline_content(content, DELIMITERS, pure_markdown=True)

    assert traced.markdown == f"at [{url}]({url})."
    assert traced.source_range((1, 0), 0, len(url)) == (4, 4 + len(url))
    assert traced.span_range((1,)) == (3, 3 + len(f"[{url}]({url})"))
    assert traced.source_range((2,), 0, 1) == (len(traced.markdown) - 1, len(traced.markdown))


def test_escapes_belong_to_their_source_character() -> None:
    traced = trace_inline_content([_text("a_b&amp;")], DELIMITERS)

    assert traced.markdown == "a\\_b&amp;amp;"
    assert traced.source_range((0,), 1, 2) == (1, 3)
    assert traced.source_range((0,), 3, 4) == (4, 9)
    assert traced.source_range((0,), 0, 8) == (0, len(traced.markdown))


def test_style_wrappers_and_formula_delimiters_have_no_source() -> None:
    traced = trace_inline_content(
        [_text(" bold ", "bold"), EquationInlineSpan(type="equation_inline", content="x")], DELIMITERS
    )

    assert traced.markdown == " **bold** $x$"
    assert traced.source_range((0,), 1, 5) == (3, 7)
    assert traced.span_range((0,)) == (0, 10)
    assert traced.source_range((1,), 0, 1) == (11, 12)
    assert traced.span_range((1,)) == (10, 13)
    assert InlineEmission((0,), 1, 3) in traced.emissions


def test_link_label_brackets_are_escaped_with_their_character() -> None:
    content = [HyperlinkSpan(type="hyperlink", url="https://e.x", content=[_text("a[1]")])]
    traced = trace_inline_content(content, DELIMITERS, pure_markdown=True)

    assert traced.markdown == "[a\\[1\\]](https://e.x)"
    assert traced.source_range((0, 0), 1, 2) == (2, 4)
    assert traced.source_range((0, 0), 0, 4) == (1, 7)


def test_many_to_one_rewrites_reject_inner_boundaries() -> None:
    traced = trace_inline_content([CodeInlineSpan(type="code_inline", content="a\r\nb")], DELIMITERS)

    assert traced.markdown == "`a b`"
    assert traced.source_range((0,), 0, 3) == (1, 3)
    assert traced.source_range((0,), 0, 2) is None


def test_source_range_rejects_empty_ranges() -> None:
    traced = trace_inline_content([_text("a")], DELIMITERS)

    with pytest.raises(ValueError):
        traced.source_range((0,), 0, 0)
