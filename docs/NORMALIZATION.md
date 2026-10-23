# Explicit display-text normalization

Raw parsing preserves format-specific extraction semantics. Call
`normalize_text(document, unicode_form=None, drop_soft_hyphens=True, limits=None)` to obtain an independent
validated copy for text consumers. CLI equivalents are `--normalize-text` and
`--nfc` (the latter also enables cleanup).

```python
from legacy_office_parser import parse, normalize_text
source = parse('example.rtf')
clean = normalize_text(source, unicode_form='NFC')
```

The operation maps CRLF, CR, VT, FF and NEL to LF, preserves TAB/LF and spaces,
removes other C0/C1 controls and DEL, and replaces surrogate code points with
U+FFFD. By default it also removes U+00AD SOFT HYPHEN, an intraword optional
line-break hint, so `co\u00adoperate` becomes `cooperate`. Pass
`drop_soft_hyphens=False` to preserve it; this parameter accepts only a Boolean.
Raw parsing still retains soft hyphens. CLI `--normalize-text` and `--nfc` use
the default removal policy.

NFC is optional; compatibility normalization is not performed. U+200B ZERO WIDTH
SPACE is preserved: it can separate words, so deleting it could join distinct
words. There is no broad deletion of Unicode format characters. Visible hyphens,
nonbreaking hyphens, joiners, bidi characters and meaningful whitespace remain.
The operation does not remove markup, hidden content or active instructions from
a downstream prompt. See [Unicode line breaking](https://www.unicode.org/reports/tr14/)
and [soft-hyphen tests](NORMALIZATION.md).

Paragraphs, cell display strings, slide title/body/notes/comment text, sheet
names/drawings and pooled text stories are normalized. Verified structured
projections are reconstructed from normalized atoms so a structural paragraph
separator is not consumed as the second half of a source CRLF. Nested cells
are processed before their containing projections.

Spreadsheet `value` and `formula`, authorship metadata, source positions,
anchor paths and warning messages are unchanged. In particular, typed source
strings can still contain controls: this API cleans display text, not every
metadata string. Plain extraction remains available in the original document.
A normalization warning records a changed result; repeated normalization is
idempotent for supported reader results.

The input and output must both fit the selected Limits. Removing controls does
not bypass input-model budgets; NFC can increase codepoint counts and therefore
fail the output budget. Cyclic models are rejected. Cloning/serialization uses
an iterative model walk, but downstream JSON encoders have their own depth and
memory limits. This API is not an HTML sanitizer or an execution sandbox.
