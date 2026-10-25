# HTML-free Markdown

Use `render_markdown(document, pure_markdown=True)` or
`MarkdownRenderOptions(pure_markdown=True)` with the shared render API.
The default remains HTML-enhanced Markdown.

The HTML-free variant uses GFM tables and strikethrough. HTML bold, emphasis,
links, and images become Markdown syntax. Underlining, super/subscripts, colors,
and emphasis dots retain their text without their visual styling. Page footnotes
remain visible text. Details are expanded with a visible summary. Algorithm and
preformatted blocks become fenced code. Complex tables become rectangular GFM
tables with blank cells in place of merged cell spans; nested tables are flattened.
HTML anchor targets are removed, so links to custom anchors may no longer resolve.

Literal HTML inside code blocks, inline code, and formulas is preserved as literal
content. Relative image paths are retained. The converter does not fetch remote
images or turn remote resources into local files.

`docvortex.render.pure_markdown.convert_to_pure_markdown(markdown)` returns a
`PureMarkdown` containing the converted string and an ordered tuple of
`MarkdownEdit` replacements. Positions refer to Unicode codepoints in the input.
`translate_range(start, end)` maps source ranges to output ranges. Edits flagged
`coarse` replace an entire structure; downstream source maps must discard finer
ownership claims inside those structures rather than inventing word positions.
`coarsens_range(start, end)` checks for such a replacement using the source range.
