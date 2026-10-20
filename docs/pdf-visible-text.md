# Public visible PDF text evidence

Raw character APIs keep their default behavior, including hidden OCR text.
Consumers that align text with a rendered page can explicitly request the
existing clipping/paint-aware view:

```python
from docvortex.document.pdf import PDFDocument

with PDFDocument("document.pdf") as document:
    page = document[0]
    geometry = page.get_chars_with_geometry(visible_only=True)
    snapshot = page.get_snapshot(visible_only=True)
    owned_text = page.get_text_snapshot(visible_only=True)
```

The same keyword is accepted by `PDFPage.get_chars`,
`PDFDocument.get_page_chars`, `get_page_chars_with_geometry`, and
`get_page_snapshot`. The owned-text method returns `None` in reference mode;
the geometry and full-snapshot interfaces work with both compute backends.

Use one visibility policy consistently for characters, side maps, span ownership,
and rendering provenance. Raw and visible snapshots have separate weak-cache
identities and do not contaminate each other. Raw PDF character indices remain
source identities, not dense offsets into the filtered list. Raw character count
limits still use the unfiltered count.

Visibility reuses the shared PDF implementation: fully clipped/unpainted glyphs
are excluded, partially clipped glyphs keep their visible geometry, and nested
Form clipping and page rotation are respected. This does not infer words from
pixels or delete tokens based on spelling. Text inside a scan's hidden OCR layer
is deliberately not part of the visible-only view; consumers needing raw OCR
text should keep the default policy.
