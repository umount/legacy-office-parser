# ODF optional-part refusal audit

Baseline: commit `84b34520967bd6523f9cb85fa8c726367d2c7778`. The isolated copy
contains no uncommitted DOC work. This audit changes no runtime code and requires
no new diagnostic identifier.

## Result and primary contract

No concrete refusal of the audited absent or empty optional structures was found.
Do not introduce a broad exception handler or silently reinterpret malformed XML
as a missing part.

[ODF 1.3 Part 3, section 2.2.1](https://docs.oasis-open.org/office/OpenDocument/v1.3/os/part3-schema/OpenDocument-v1.3-os-part3-schema.html)
allows optional package files, but requires `styles.xml`, `meta.xml`,
`settings.xml`, and `content.xml` to be well-formed XML when present. Sections
3.1.3.2–3.1.3.5 separate content, styles, metadata, and settings. Section 3.15
separates common, automatic, and master styles. Section 19.510 requires referenced
parents to exist and forbids automatic styles as parents. A missing reference
is not evidence to select an unrelated stored style.

An empty styles root or empty style container is different from a zero-byte or
truncated XML member. The former already works; the latter is corrupt input and
still fails. Metadata/settings are not opened by this extractor; their stored
values do not supply document text.

[ODF 1.3 Part 2, sections 2.2 and 3.2](https://docs.oasis-open.org/office/OpenDocument/v1.3/os/part2-packages/OpenDocument-v1.3-os-part2-packages.html)
requires a manifest, including encryption declarations where applicable. The
existing missing-manifest warning is compatibility behavior, not evidence that
the manifest is optional in conforming packages. Existing manifest/MIME and
package security policies are retained.

Part 3 section 2.2.1 permits generic styles-only document packages. This audit
does not expand the parser's main-body extraction contract to such packages or
synthesize an empty body for missing `content.xml`. Required content, body/type
validation, encryption rejection, and global resource limits are unchanged.

## Audited runtime paths

- `_odf_package.read_package`: absent styles, optional metadata/settings, manifest
  and MIME handling, duplicate members, encryption flags/declarations, ZIP byte
  and expansion limits, and malformed XML handling.
- `visibility_definitions`, `visibility_scope`, `text_display`, `hidden`: empty
  maps, unresolved/duplicate references, scope boundaries, same-family defaults,
  cycles and inherited-style depth limits. Missing definitions produce existing
  conservative fallback diagnostics instead of rejecting the document.
- `used_masters` and `masters`: absent master definitions return no stories;
  missing/ambiguous master references omit affected stories; empty selected
  header/footer content is harmless. Resource depth failures remain errors.
- `note`, `story`, `finish_notes`: absent notes require no ownership records;
  empty note content retains an empty paragraph body range without invented text.
  Malformed/unclassified note structures follow existing diagnosed omission.
- Main ODT/ODS/ODP traversal: empty text/spreadsheet/presentation collections are
  accepted. Missing/ambiguous `office:body` and wrong body type remain errors.
- Tables, repeated stories, drawings, and inline objects: existing empty-structure
  and record/cell expansion tests retain limits; optional status never resets
  the shared budgets. Unselected object representations remain unexpanded.

## Original synthetic verification

`tests/test_odf_optional_parts_audit.py` adds 45 cases. The package helper writes
an uncompressed first `mimetype` member and explicit manifest entries for each
XML member. Positive cases cover all three supported ODF families, absent and
empty style structures, unopened metadata/settings, empty main collections,
empty master stories, empty notes, and missing visibility styles. Robustness
cases are not a claim that every XML fixture is schema-conforming.

Negative cases preserve failure for zero-byte/truncated styles, declarations,
missing/empty/wrong main structure, excessive optional-style nodes, and an
oversized ignored metadata member. Such member inventory checks remain global,
even when the member's contents are not interpreted.

No private corpus, converters, dependency changes, source-text inventions, or
runtime exception suppression were used. Missing styles and auxiliary metadata
are not a reason for a new runtime patch based on the evidence obtained here.
