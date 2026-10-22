# Explicit soft-hyphen normalization

## Decision and primary evidence

`normalize_text(document, *, drop_soft_hyphens: bool = True, ...)` removes only
U+00AD SOFT HYPHEN from the existing display-text fields. Passing `False` keeps
it. The option accepts actual booleans only: integers, strings, and `None` raise
`TypeError`. Raw parsing is unchanged. CLI `--normalize-text` and `--nfc` use the
new default; running the CLI without either option still returns raw text.

[Unicode Standard Annex #14, section 5.4, Use of Soft Hyphen](https://www.unicode.org/reports/tr14/)
describes U+00AD as an invisible marker of a preferred intraword line break,
unlike a visible hyphen. Dropping that layout marker from explicitly normalized
search text lets `co<U+00AD>operate` become `cooperate`. This is an application
policy for extraction/search, not a requirement of NFC or a guarantee about
all BM25 tokenizers. Rendering at a discretionary break can involve
language-specific spelling changes; this change does not reconstruct those.

[Unicode 17.0, section 23.2.1, Line and Word Breaking](https://www.unicode.org/versions/Unicode17.0.0/core-spec/chapter-23/)
distinguishes U+200B ZERO WIDTH SPACE as a word/line break opportunity, including
in languages without visible word spacing such as Thai, Myanmar, Khmer, and
Japanese. U+200B therefore remains intact. No general-category `Cf` filtering
is introduced. Joiners, bidi controls, BOM, visible hyphens, and nonbreaking
hyphens retain their previous behavior. No new cross-line dehyphenation occurs.

## Ownership and bounds

The implementation adds strict option validation and one conditional string
replacement inside the existing display-text normalizer. It does not modify
parser decoding, model traversal, projection ownership, the diagnostic registry,
CLI flags, or Unicode normalization forms. The extra pass is linear in each
already-budgeted display string and cannot increase its size. The existing
pre-normalization validation prevents using removable characters to bypass
limits; post-normalization validation remains in force, including NFC growth.
No mutable global translation state, new runtime dependency, file access, or
network access is added.

Existing display fields are normalized on the cloned document: paragraphs,
cell text and nested blocks, pooled stories and their structured projections,
sheet names/drawings/cell display text, slide titles/body/notes/comment text.
Spreadsheet typed values and formulas, comment authorship, note/comment source
positions, anchor paths, body block ranges, headings, and structural metadata
remain unchanged. An atom consisting only of U+00AD becomes an empty atom;
its block and note range are retained. Existing projection separators remain
owned by the structure.

A changed result uses the existing `text_normalized` diagnostic. Reapplying
normalization produces no additional diagnostic and the same serialized model.
`drop_soft_hyphens=False` disables only this removal, not existing control cleanup
or requested NFC.

## Synthetic regression evidence

`tests/test_normalization_soft_hyphens.py` uses authored inputs only:

- DOC FIB/CLX streams in both compressed and UTF-16 pieces: source 0x1F decodes
  to U+00AD, which remains in raw output until explicit normalization.
- RTF escaped `\-` and Unicode `\u173?`: raw U+00AD is retained.
- ODT literal U+00AD inside `text:p`; no invented soft-hyphen XML element.
- Every existing normalized model projection, typed values and formulas,
  source positions and note ranges, U+200B and other format characters,
  strict option types, idempotence, source immutability, exact budget boundary,
  NFC interaction, and CLI raw versus requested normalization behavior.

## Validation scope

Final focused run:

- `python -m pytest -q tests/test_normalization*.py tests/test_cli.py`:
  **46 passed**.
- `python -m ruff check src/legacy_office_parser/normalization.py tests/test_normalization_soft_hyphens.py`:
  **passed**.

The earlier DOC/RTF/ODF core plus normalization/CLI regression run completed
with **225 passed**. The independent review was reported by the integrator as
clean with **57 passed**; that is a separate review result, not the count of the
focused command above. No full-suite, build, tokenizer benchmark, or external
renderer result is claimed here. Integration-wide tests and build validation
remain a separate step.

The implementation delta is limited to `src/legacy_office_parser/normalization.py`,
with original synthetic regressions in `tests/test_normalization_soft_hyphens.py`
and this research note. Parser decoding, shared documentation, version metadata,
and the diagnostic registry are outside this change.
