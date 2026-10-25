# HTML-free Markdown

Use `render_markdown(document, pure_markdown=True)` or
`MarkdownRenderOptions(pure_markdown=True)` with the shared render API.
`render_single_block(..., pure_markdown=True)` and
`docvortex.render.fragments.render_inline_content(..., pure_markdown=True)`
select the same dialect for partial rendering. The default remains
HTML-enhanced Markdown.

The renderer emits the HTML-free dialect directly; there is no post-processing
pass. Output is GFM (tables and strikethrough) without raw HTML blocks or inline
HTML. Rendering blocks one by one and joining them with blank lines yields the
same text as rendering the whole document, so callers can derive source maps
from the public render functions.

| Source feature | HTML-free output |
| --- | --- |
| bold, italic, strikethrough and their combinations | `**`, `*`, `~~` (for example `~~**x**~~`) |
| underline, emphasis dots | text only |
| superscript / subscript | `^x` / `_x` prefix (`10^-3`, `H_2O`) |
| styled whitespace (form gaps) | `_` (underline) or `-` (strikethrough) per character |
| hyperlinks with complex label styles | `[label](url)` with the representable styles |
| bookmark anchors, links to `#anchor`, index links | omitted; the link label remains as text |
| page footnotes | plain paragraph |
| image / chart details | expanded: bold summary followed by the content |
| algorithms | fenced code block with plain text and delimited formulas |
| simple tables | GFM table (unchanged from the default dialect) |
| complex tables | rectangular GFM table: merged cells keep content in the first cell and leave the others blank; line breaks and block content become spaces, list items are joined with `; `, nested tables are flattened to text |
| other embedded HTML | known structure becomes Markdown (paragraphs, headings, lists with their start number, `pre` as fenced code, images, links, formulas); unknown tags keep their text; scripts, styles, forms, embeds and comments are dropped |

Literal text that looks like HTML is emitted as entities (`&lt;div&gt;`), which
CommonMark renders as text. Relative image paths are retained; remote images
are not fetched.
