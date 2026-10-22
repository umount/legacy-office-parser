# DOC header source identities

This helper decodes source slots, not rendered pages. It does not change pooled
text, clone inherited contents, interpret page-selection flags, or execute any
embedded content. Only original public synthetic fixtures are used.

## Primary format evidence

[MS-DOC §2.3.3, Headers](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/8465bee7-6c79-45a9-812e-58b0c5fd6cdc)
places six note-separator stories before six header/footer stories per section.
The separator order is footnote separator, continuation separator, continuation
notice, then the same three endnote types. Each section contributes even header,
odd header, even footer, odd footer, first header, first footer. Nonempty slots
end with a guard CR outside their contents. Header/footer contents additionally
end with CR; separators need not contain complete paragraphs. Equal adjacent
boundaries indicate a source-empty slot. Empty header/footer slots inherit the
previous section's corresponding type; the first section has no predecessor.

[MS-DOC §2.8.22, Plcfhdd](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/8f336b7e-66cb-4346-9fd4-88ede9a4a9db)
defines a CP-only PLC. With M entries, M−2 are source slots. All boundaries
except the undefined final entry must lie below `ccpHdd`; the penultimate entry
must equal `ccpHdd−1`. The final entry is ignored even when out of range or
nonmonotone. The helper rejects decreasing meaningful boundaries and unassigned
prefixes rather than silently omitting source text.

[MS-DOC §2.8.26, PlcfSed](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/68a959a6-11e0-4f3e-9a99-76ca8cc4dddc)
uses N+1 CPs and N twelve-byte SEDs, giving `16*N+4` bytes. CPs cannot repeat;
the terminal CP must reach the main story but may extend into auxiliary text.
The helper validates increasing CPs, first CP zero, internal starts inside the
main story, and terminal coverage. It does not inspect SEPX or section-break
characters: the existing caller validates those. A zero-section PLC is accepted
only with an empty main story for synthetic compatibility, not as a claim about
ordinary authored documents.

## Integration contract

```python
decode_header_ranges(plc, story_bytes, limits, section_count=None,
                     *, record=None, warn=warnings.warn)
# -> list[SourceHeader] | None

decode_section_count(plc, main_count, limits, *, record=None)
# -> int | None
```

Pass the original, unnormalized UTF-16LE header subdocument slice as
`story_bytes`. Its length must match the declared `ccpHdd` (the caller supplies
that slice). `section_count` must come from validated PlcfSed, either the
existing `_sections()` or the auxiliary helper; do not infer it from header
slots. The helper checks exact agreement with `6 + 6*section_count`.

`SourceHeader` is frozen and has fields `start`, `end`, `section`, `kind`,
`variant`, `ordinal`. Ranges are half-open relative UTF-16 CPs, not Unicode
scalar offsets. Exactly one verified guard is removed from each nonempty
source slot. Header/footer content paragraph marks remain. Ordinals are
one-based source PLC slots, without filtering empty entries.

Kinds are `header`, `footer`, `footnote_separator`, `endnote_separator`.
Header/footer variants are `even`, `odd`, `first`; note variants are `separator`,
`continuation_separator`, `continuation_notice`. Separator section is `None`;
other sections are one-based. The helper emits no `inherited_from` field.
The caller can resolve empty header/footer slots to previous source ordinals
of the same kind and variant without duplicating text. A header containing a
blank paragraph has a nonempty content range and must not inherit. A guard-only
separator has an empty content range but is not a source-empty slot; separator
inheritance must not be inferred from range length.

Absent PLC with nonempty story returns `None` and warning code
`doc_header_plc_missing`. Absent validated section count returns `None` and
`doc_header_section_count_missing`, after checking the present PLC and guards.
The latter deliberately emits no partial separator identities. An absent PLC
and empty story return `[]`. The caller retains its legacy whole-story fallback
for `None`. The optional `warn` sink receives a string-compatible `CodedWarning`.
Malformed present data and exhausted budgets raise; neither becomes fallback.
`decode_section_count` itself returns `None` without a warning for absent PLC.

Pass the aggregate `record` budget callback. Header decoding charges all M CP
entries, including sentinels, before boundary-list allocation. Section decoding
charges N SEDs plus N+1 CPs. Each helper also applies local record limits and bounds PLC bytes by
`max_stream_bytes`. Decoded header UTF-16 is bounded only by its CP count
against `max_text_chars`, not by `max_stream_bytes`: compressed source text
can expand during decoding. The regression covers 63 source CPs (126 decoded
bytes) with a 56-byte PLC and a 63-byte stream limit, plus missing-PLC fallback
and rejection at a 62-CP text limit; the caller owns aggregate text/stream budgets and the
initial bounded stream reads. The helpers do not copy the complete story or
allocate according to untrusted CP values. Avoid charging section parsing twice
if the caller already validated it: pass its existing section count instead.

The caller must preserve legacy pooled projection independently, including
guards and its existing whitespace behavior. Metadata/body parsing uses the
returned content ranges. This module does not determine block ranges,
visibility, fields, page applicability, or inheritance links.

## Independent evidence and validation

The tests read `tests/fixtures/doc_headings/authored.doc` through a fixture-only
OLE/FIB/CLX walk, without importing the production DOC decoder. This original
LibreOffice-exported fixture has main/footnote/header counts `203, 0, 28` and
one section. Literal Plcfhdd entries are:

```
0, 0, 0, 0, 0, 0, 0, 0, 25, 25, 25, 27, 27, 29
```

Its undefined final CP, 29, exceeds the header length and is correctly ignored.
Ordinal 8 is section 1 odd header, content `[0,24)` containing
`Header heading specimen\r`. Ordinal 11 is section 1 first header, content
`[25,26)` containing a paragraph CR. The other ten slots are source-empty.
The first-page blank paragraph remains distinct from an absent/inherited slot.

Independent deterministic byte specimens cover all six separators and all six
section variants, a second empty section, supplementary Unicode CP accounting,
guard-only separators, undefined sentinels, malformed sizes/order/bounds,
section disagreement, missing evidence warning codes, and aggregate callbacks.
The helper checks CR guards itself; caller-side guard verification is not needed.

Validation in `/tmp/legacy-next-024`:

- Focused tests: **48 passed**.
- Header, section, note, and textbox regression tests: **223 passed, 1 skipped**
  (the existing optional live-conversion test).
- After main integrated `_parse_headers`, the same tests plus all eight
  `test_doc_auxiliary_stories.py` tests: **231 passed, 1 skipped**.
- Ruff on the two owned Python files: passed.

Runs used `PYTHONDONTWRITEBYTECODE=1`, pytest `-p no:cacheprovider`, and Ruff
`--no-cache`. This sidecar performed no converter run, production parser integration,
model/registry edit, private-input access, or commit. Main owns integration,
models, and warning-code registration; the combined test run exercises that
integration without changing those files.

Follow-up decoded-story limit correction: header helper and auxiliary-story
tests **60 passed**; Ruff on the two owned Python files passed. Only PLC bytes
use the local stream-byte limit; caller-side actual OLE stream limits remain
unchanged.
