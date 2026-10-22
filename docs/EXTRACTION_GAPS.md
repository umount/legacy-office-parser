# Remaining extraction gaps

Working register after 0.21. Each item requires a verified example, independent
expected results, negative tests and limits, API checks, and comparison with an
external reader where it supports the construct. The absence of warnings alone
does not establish completeness.

## Completed in 0.11

- DOC: separation using explicit table properties, including positioning and
  styles. Checking the first cell paragraph is the next separate stage.
- PPT: ordinary text from active masters, excluding placeholders and hidden shapes.
- RTF: table structure in auxiliary stories.

## Completed in 0.12

- ODT: table structure in auxiliary stories and bounded repetition.
- XLS: a verified nonnegative subset of conditions; negative conditional values
  and ambiguous thresholds remain open.

## Completed in 0.13

- DOC: table boundaries based on the first paragraph of the first cell, including
  inherited frame properties. Synthetic cases and the existing private corpus
  were checked.
- ODT: text and tables from inline text objects; one frame representation is
  selected, with a shared budget and no link access. Confirmed through independent
  LibreOffice readback.
- RTF: explicit text from standalone legacy drawings (`do/dptxbxtext`), preserving
  tables and control-word scope. Confirmed with an authored LibreOffice example.
- PPT: stored static footers and dates with verified visibility; computed fields
  remain outside this subset.

## Completed in 0.14

- DOC: separate note bodies, source CPs, visibility flags and paragraph/cell
  paths; the existing text API is preserved. Authored binary examples and negative
  tests do not conceal losses introduced by LibreOffice conversion.
- ODT: rectangle, ellipse and custom-shape text in the shared textbox story.
- XLS: three verified currency labels, comma scaling and optional trailing
  fractional digits after a mandatory decimal digit. Nineteen cases are compared
  using the same XLS with its original FORMAT records preserved.

## Completed in 0.15

- DOC: unconditional table-style visibility using the innermost row context,
  followed by paragraph/character/direct overrides. Specification and LibreOffice
  behavior differ; the research and tests explicitly record this.
- ODS: ordinary drawing text associated with its sheet in `Sheet.drawings`.
- PPT: substitution of verified stored footer text in inline FooterMC, preserving
  equivalence between alternative representations of the same shape.

## Completed in 0.16

- DOC: conditional CFVanish 0/1 for complete rectangular tables without merges,
  with proven boundaries and edge, corner and band flags. Ambiguous cases retain
  unconditional visibility and diagnostics; note-reference visibility is `unknown`.
- PPT: `Slide.comments` stores the text, author and initials of comments on the
  current slide. Text follows notes in the projection; an empty field preserves
  the previous JSON shape.
- The note oracle distinguishes a DOC table from its verified textbox
  representation in newer LibreOffice, without weakening general structural checks.

## Completed in 0.17

- XLS: empty ordinary numeric sections and a validated empty fourth text section;
  raw values and formula flags remain available. A preserved XLS is checked
  against LibreOffice without resaving its source FORMAT records.
- DOC: PLC-owned comments, authors, initials, reference-container paths and
  verified ordinary source selections. Shared body blocks avoid duplicate text.
  Unproven ownership is omitted with diagnostics; complex selections remain unknown.
- RTF: explicit type-136 WordArt with enable flags and a bounded literal ASCII
  property grammar. Independent LibreOffice readback confirms the original example.
  Fallback-only shape probes did not establish a safe recovery rule.

## Completed in 0.18

- RTF: Unicode and Windows-1252/1251/932 text in the verified explicit WordArt
  subset, including scoped fallback counts and surrogate pairs. Nine authored
  fixtures match independent LibreOffice extraction; malformed properties are
  omitted as a whole. Nested formatting, other code pages and fallback-only
  ownership remain outside this subset.

## Completed in 0.19

- XLS: one text placeholder with quoted/escaped prefix and suffix in an ordinary
  fourth section. Raw strings and cached-formula markers remain available;
  distinct display strings are budgeted before allocation. Twelve preserved-XLS
  cells match independent LibreOffice CSV extraction.
- DOC: ordinary cross-paragraph comment selections, including empty paragraphs,
  and multi-paragraph spans within a source cell with a proven terminator.
  UTF-16 source coordinates and reference anchors remain distinct. Original
  DOC/readback evidence and independent boundary tests cover the new subset.

## Completed in 0.20

- DOC: explicit reply depth and retained-parent ordinal from validated AtrdExtra
  preorder metadata. Missing ancestry does not drop bodies or invent roots.
  An authored binary metadata probe establishes source relationships; LibreOffice
  preserves its bodies but flattens the tree on resave, which is recorded as loss.
- XLS: quoted/escaped literal-only fourth text sections, including empty display,
  with raw typed values retained. Thirteen preserved-XLS cells match the
  independent LibreOffice CSV oracle. Fraction formatting remains deferred.

## Completed in 0.21

- DOC: explicit paragraph heading levels 1–9 from fixed styles and stored outline
  properties, including bounded style inheritance, direct and compact overrides.
  Headings remain in their source cells/stories; ordinary paragraphs keep the
  previous JSON shape. Style increment/permutation remains explicitly unsupported.
- Documented structured XLS row assembly and consumer-owned DOC heading paths.
  These adapter policies do not change the library's flat-text projection.

## Next areas to verify

- DOC: header/footer and frame identities; ink and complex
  source selections crossing cells, rows, sections or other unproven boundaries.
- DOC: remaining conditional table styles and explicit geometry that does not
  require page layout.
- PPT: text in extensions and embedded passive documents; agreement with a
  converted presentation does not substitute for understanding unknown constructs.
- XLS: general localization, fraction formats, conditional hiding and wider
  text-section formats. Hidden values must remain available in typed data.
- RTF: legacy shape text without primary shptxt; safe selection between primary
  and fallback representations without duplication.
- ODF: passive text in embedded objects and extensions where the format defines
  its document ownership. External resources are not opened.
- Expansion of a legally usable real-world corpus, kept separate from private files.

## Additional evidence required

Negative values in conditional XLS masks and fully optional fractional digits
still return the original value with a warning. Available primary sources have
not established unambiguous rules for signs and decimal-point removal;
individual Calc results do not replace that contract.
Research: `research-xls-conditions.md`.

## Scope boundaries

Macros, formulas, scripts and commands are not executed, and external links are
not followed. Page rendering, exact pagination, styling, OCR and image extraction
are outside the current text-parser contract. Pre-Word-97 DOC, pre-BIFF8 files
and encrypted documents require separate decoders; fixing known cases in the
supported formats does not add support for them. Full equivalence to an office
application on arbitrary files is not promised.
