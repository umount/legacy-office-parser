# Synthetic ODT notes fixtures

These documents were authored from scratch for this project. All prose, XML,
and expectations are original test data, available under the repository's
Apache-2.0 license. No user documents or external document corpus were used.
`example.org` is only an inert hyperlink target; conversion does not require it.

- `ordinary.odt` and its readable `ordinary.content.xml`: Cyrillic main text,
  two footnotes and two endnotes; the first of each has two paragraphs, the
  second is anchored in a table cell. One cell also contains a hyperlink.
- `repeated.odt` and `repeated.content.xml`: two repeated rows, each containing
  two repeated footnote-bearing cells followed by an endnote-bearing cell.
- `*.expected.json`: independently authored textual expectations, not output
  captured from this parser. Notes are arrays of paragraph arrays. The parser's
  string fields flatten these with two newlines; `main` lists visible paragraphs
  in reading order, including table cells.
- `*.lo/{document,footnotes,endnotes}.xml`: unmodified XML parts from DOCX
  conversion with LibreOffice 7.4.7.2, `40(Build:2)`, on 2026-10-21. Only these
  relevant parts are retained; no generated DOCX profiles or metadata are needed.

The ODT archives contain only mimetype, content.xml, and a minimal manifest.
`mimetype` is first and uncompressed; ZIP timestamps are fixed to 2026-01-01.
The readable content.xml files exactly match the respective archive members.

## Independent LibreOffice comparison

Conversion uses `--headless --convert-to 'docx:Office Open XML Text'` and a unique
`-env:UserInstallation=file:///...` per invocation, with a 45-second timeout.
The opt-in test additionally kills the entire process group on timeout:

```sh
ODF_NOTES_LIBREOFFICE=1 .venv/bin/python -m pytest tests/test_odf_notes.py -q
```

Ordinary fixture: all five main paragraphs, both footnotes (three paragraphs),
and both endnotes (three paragraphs) match the independent expectations and
parser output exactly. The comparison reads `w:t` text only, excluding automatic
`w:footnoteRef`, `w:endnoteRef`, main-text anchors, and the leading citation tab
inserted by LibreOffice. Separator/continuation pseudo-notes are excluded by
`w:type`, not hardcoded IDs. No digits are removed and no textual whitespace is
normalized. These fixtures contain no authored tabs, line breaks, or custom
citation labels; this comparison helper is not a general DOCX text extractor.

## Repeated content: specification and observed difference

ODF 1.3 Part 3 sections 9.1.3, 9.1.4, 19.679 and 19.681 describe repetition of
adjacent cells/rows with identical content:
https://docs.oasis-open.org/office/OpenDocument/v1.3/os/part3-schema/OpenDocument-v1.3-os-part3-schema.html

Our interpretation is that note bodies are part of that repeated content.
The parser expands notes in row-major order, including all notes within each
cell, and charges the expanded text, separators and note-body table cells to
resource limits. It does not deduplicate by `text:id` or identical body text.
No claim is made about rendering fresh citation numbers or resolving identities
of repeated anchors; the extraction model stores only note body strings.

For `repeated.odt`, LibreOffice 7.4.7.2 imports the repeated columns (two footnotes)
but ignores the repeated row: its DOCX has one row, two footnotes and one endnote.
The parser retains two rows, four footnotes and two endnotes. The saved XML test
records this difference explicitly; it does not treat LibreOffice's row loss as
the desired expectation. The live comparison test covers the ordinary fixture;
the recorded repeated-case behavior is specific to the stated LibreOffice build.

Remaining limitations: no citation labels, anchor mapping or pagination in the
model; nested notes and malformed/unclassified notes remain unsupported. This
small fixture set is not a claim of complete LibreOffice parity.
