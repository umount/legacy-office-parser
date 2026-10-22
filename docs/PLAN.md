# Work plan

## Current purpose

Provide a reliable representation of office document data for LLMs. Tasks are
prioritized by text loss, disrupted reading order, table relationships,
and the meaning of values. Units and percentages are part of the data's meaning.
Executing active content, fetching resources, and reproducing exact page layout
are out of scope. The stages below are retained as a history of development.

## First-version goal

A small, standalone Python package for DOC/PPT with one runtime dependency:
`olefile`. DOC: text and table structure; PPT: text by slide and notes.
Only the binary Word/PowerPoint 97–2003 formats. No network or office runtime.

## Stages and criteria

1. Research and contract: study existing implementations and format
   limitations; define errors, the model, and limits.
2. Corpus: create original documents with explicit expected cells,
   slide order, Cyrillic text, and notes. Private files belong only in `tmp/`.
3. DOC: FIB → CLX → text pieces, then PAPX/FKP/SPRM → paragraphs/tables.
   Do not replace structural parsing with heuristics; identify unsupported cases.
4. PPT: Current User → UserEdit chain → persist directory → active
   slides/notes. Preserve empty slides and their numbers; do not index old versions.
5. Validation: unit tests for corrupt structures, an end-to-end synthetic corpus,
   a local private corpus, text/table comparisons with LibreOffice, and metrics.
6. Delivery: wheel, CLI, documentation of limitations, and reproducibility instructions.

## Readiness

The first version must not be declared a complete replacement for LibreOffice
based solely on passing unit tests. Known expected results and analysis of
discrepancies are required. Record issues found in real documents without
quoting private content.

Record the actual status and limitations in `TESTING.md` after test runs.
Save work in intermediate commits; publication is a separate step.

## First-iteration status

Stages 1–6 are implemented: package, API/CLI, parsers, original corpus,
validation, and build. Limitations and results are listed in `TESTING.md`.
Next steps: expand the real-world PPT corpus, investigate DOC discrepancies,
and gradually address unsupported constructs with individual regressions.
The next agreed formats are listed below; implementation proceeds in stages.

## Target format support

The project's ultimate goal is content extraction without LibreOffice for:
DOC, XLS, PPT, RTF, ODT, ODS, and ODP. The initial DOC/PPT stage does not mean
that this goal has already been achieved. Rendering and converting the visual
appearance of documents are excluded: the goal is text and structure extraction.

The next stages will be defined after reviewing existing implementations and specifications:

- XLS: sheets, cell types and values, rows/columns, and merges;
  define a separate policy for formulas and cached results.
- RTF: code pages, Unicode escapes and fallback bytes, nested groups,
  tables, and exclusion of control/embedded data from text.
- ODT/ODS/ODP: ZIP/XML, text and tables, sheets and slides; limits on decompression,
  repeated rows/cells, and XML structures.

Each format needs an independent module, a public contract,
an original synthetic corpus, and validation against real files.

Delivery remains a single package with a unified API and internal format modules.
Existing implementations provide algorithms, selected necessary components,
and regression cases; adding a separate large dependency for each
format is not the target architecture. Borrowed components must carry
source and license notices. Errors, limits,
format detection, and the result wrapper remain shared; sheets/cells, tables,
and slides retain their own structure. The implementation order is not yet fixed.

## Second iteration: one package for seven formats

RTF, XLS BIFF8, and ODT/ODS/ODP are implemented; the shared API and CLI are extended.
Sparse sheets now include value types, merges, and cached
formula results. There is still only one runtime dependency: `olefile`.
Existing solutions were studied before implementation: xlrd, striprtf/WordCraft, and odfpy/OASIS.

All seven formats have original documents with independent expectations.
The initial limitations of each new format, comparison methodology,
and actual results are listed in `TESTING.md` and the format-specific research files.
Full equivalence with LibreOffice is not claimed: subsequent improvements are selected
based on reproducible discrepancies and constructs needed for real documents.


## Quality criterion and third iteration

The goal is to extract text and the required structure at least as well as LibreOffice
on an agreed corpus covering all seven formats. Passing unit tests, the number of supported
extensions, and matching sets of words do not establish this on their own.

- Compare text in reading order; separately check tables, coordinates,
  merges, cell types and values, slide order, and notes.
- Address every confirmed loss with an independent regression and a fix.
- Distinguish parser defects, errors in reference conversions, and differences in representation.
  Do not adapt the output to reproduce content loss in LibreOffice.
- Explicitly identify unverified and unsupported constructs. A warning
  reports a gap but does not replace fixing it.
- Check the local corpus without publishing private content; create public
  regressions from original minimal documents.

The current iteration strengthens comparisons of structure and auxiliary stories,
adds support for ordinary ODT footnotes, and checks DOC/RTF completeness using
reproducible examples. Full equivalence is not claimed until these checks are complete.


### Third-iteration results (0.3)

Document, table, and presentation comparisons were strengthened; actual
LibreOffice checks and deterministic corrupt inputs were added to CI. Fixes cover
DOC Prm0/CSymbol and RTF merges and shape text; ODT now supports footnotes, text
frames, and selected headers/footers. Local and independent checks are described
in `TESTING.md`. Results were saved in separate intermediate commits.

Further coverage is needed for nested tables, DOC style inheritance,
rare PPT/RTF extensions, and implicit ODT pagination. These remain gaps,
not completed items. A broader real-world corpus and analysis of every
significant discrepancy are required before replacing the office runtime generally.


### Fourth-iteration results (0.4)

Nested RTF/ODT tables preserve structure and paragraph order in `Cell.blocks`;
`Cell.text` remains the complete text projection. DOC accounts for inherited
style visibility and direct hidden/deleted properties. PPT extracts WordArt
from properties of active shapes. Comparison with DOCX checks nested structure.

Remaining gaps include nested DOC tables, conditional table styles, rare format
extensions, and implicit pagination. Executing macros or formulas and fetching
external resources are outside the package's purpose.


### Fifth-iteration results (0.5)

- Nested DOC tables and tables in auxiliary stories are preserved;
  text order, grids, merges, and retained-projection limits were checked.
- Comparisons of headers/footers and frames against a DOCX reference were expanded.
  Text comparison is explicitly distinguished from unknown anchors, geometry,
  and ordering of separate stories.
- A reproducible time and memory benchmark was added for large ordinary documents
  in all seven formats, checking the amount of extracted content.
- Documentation of current coverage was updated; package checks and CI are part of delivery.
- DOC section boundaries are handled separately from manual page breaks.

A broader real-world PPT corpus, rare extensions, and XLS number formats
remain separate areas of work. Subsequent fixes must be based on
reproducible documents and independent expectations. Implicit ODT pagination
requires a layout engine and is not promised by the current extraction contract.


### After 0.5: PPT extensions and external DOC properties

A bounded subset of auxiliary PPT extensions was classified:
animation timing and numeric properties no longer imply possible text loss.
Unknown extensions retain a warning. An original 120-slide presentation
passes a complete check of its specified content without warnings.

Version 0.6 completed the external DOC table properties stage: sequential cell
operations, shared bounded traversal of HugePapx/PTableProps, an original OLE file,
independent regressions, and a LibreOffice comparison. Limitations of conditional
styles and automatic geometry are described in `research-doc-external-tables.md`.

Further work prioritizes reliable data for LLMs: text completeness and order,
table relationships, cell values, and explicit indications of incomplete
extraction. Executing macros/scripts/formulas, following links, fetching
external resources, exact formatting, and pagination are outside the plan.


### XLS numeric data (0.7)

Loss of meaningful representations of common number formats was addressed:
percentages, decimal places, grouping, and scientific notation. The original number
is retained separately; formulas are not recalculated. Unknown format patterns
are not interpreted speculatively and produce a warning.
Validation covered an original XLS, the CLI, independent BIFF cases, and
LibreOffice's displayed values.

Remaining areas within scope: DOC table rows with differing outer boundaries,
anchors for auxiliary text stories, PPT text extensions, and value formats
with units/currencies and conditional sections.
Each requires reproducible examples and an independent expected result.


### Differing DOC row boundaries (0.8)

A common grid of exact boundaries is built for explicit, strictly increasing geometry.
Missing positions are marked `omitted`; internal merges are preserved.
Tests cover nesting, vertical merges, empty cells, and the grid-expansion
budget. Comparisons do not equate a missing position with an empty cell.
Automatic geometry, conditional styles, and distinguishing adjacent tables using all
positioning properties remain limitations; details are in
`research-doc-offsets.md`. Next areas: text-story anchors,
PPT text extensions, and additional meaningful XLS formats.


### Explicit XLS number labels (0.9)

Quoted/escaped labels before/after the numeric core are preserved: units,
currency symbols, and literal percent signs. The original number remains separate.
Independent BIFF tests and an original XLS check the distinction between a literal
percent sign and scaling; LibreOffice provides an additional reference.
Details: `research-xls-literals.md`. Localized currency patterns,
conditional formats, and multi-section formats remain outside this stage.


### XLS numeric sections (0.10)

Ordinary sign-based sections were added: positive, negative, and zero
values; parentheses and explicit signs, nonempty zero labels, and standard colors.
Selection precedes rounding; original numeric values are unchanged.
All sections are validated, even if the current cell does not select them.
Details: `research-xls-sections.md`. Numeric comparison conditions,
localized patterns, and sections that hide values remain limitations.


### Structure and inherited-text extraction package (0.11)

Auxiliary RTF tables, explicit boundaries between adjacent DOC tables,
and ordinary text from active PPT masters are preserved. Each stage has independent expectations,
an original document, and limit checks; review findings were fixed.
Further work is tracked in `EXTRACTION_GAPS.md`; unfinished parts
are not considered supported merely because a related construct is extracted.


### Auxiliary ODT tables and XLS conditions (0.12)

Tables in ODT auxiliary stories retain their structure as independent copies;
the retained-text limit is checked before making additional copies.
XLS conditions are supported for a verified nonnegative subset;
negative values and ambiguous thresholds do not receive speculative
display representations. This is a partial extension, not complete support for conditional formats.
The RTF oracle was fixed for LibreOffice versions that create multiple identical
header/footer variants: each variant is checked in full.


### Passive content and story boundaries (0.13)

Boundaries between adjacent DOC tables now account for first-paragraph properties;
other additions include inline ODT text objects, standalone legacy RTF text, and static
PPT fields. Parsing retains shared limits and selects a verified representation.
Next work: separate DOC note relationships, meaningful XLS number formats,
and text visibility in table styles. The detailed register is in `EXTRACTION_GAPS.md`.


### Notes, shape text, and numeric labels (0.14)

DOC gained separate note relationships without duplicating text; ODT gained text from three
verified shape types; XLS gained bounded currency patterns, scaling,
and optional trailing digits. The package uses a single source for its version.
CI also mutates the entire original corpus rather than just the baseline files.


### Text visibility and ownership (0.15)

Unconditional DOC table-style CFVanish is applied before paragraph/direct overrides,
after establishing row context. ODS shape text is associated with its sheet,
and static inline PPT FooterMC substitutes the stored label. Embedded
execution and computed dates remain unsupported.


### Conditional visibility and comments (0.16)

A verified subset of conditional DOC CFVanish is implemented, including inheritance,
edge/corner precedence, bands, RTL, and conservative fallback when boundaries
are ambiguous. Comments on active PPT slides are represented separately with authorship.
Both paths passed independent review and negative regressions. Remaining areas
require separate evidence and are listed in `EXTRACTION_GAPS.md`.


### Source-owned comments and display semantics (0.17)

Added DOC comments with shared bodies, authors and verified source anchors;
preserved raw XLS values behind supported hidden displays; extracted a narrow,
explicitly enabled RTF WordArt subset. Each change has independent expected
results, malformed-input and budget checks, and original reference fixtures.
RTF fallback-only ownership remains unresolved rather than being guessed.
See `research-doc-comments.md`, `research-xls-hidden-sections.md` and
`research-rtf-fallback-text.md` for the contracts and evidence.

### Unicode WordArt (0.18)

Extended the verified explicit RTF WordArt subset using the existing incremental
text decoder. Unicode fallback, surrogate pairs and three proven code pages
retain shared text limits and strict shape ownership. Original LibreOffice
fixtures, independent adversarial cases and API/CLI checks cover the extension.
Fallback-only shapes and richer property grammar remain explicitly deferred.

### Text display and comment ranges (0.19)

Added bounded quoted/escaped XLS text affixes while retaining raw values, and
DOC comment selections across proven ordinary paragraphs/source cells. Both
changes have original reference fixtures, independent boundary/limit reviews,
public API/CLI regressions and installed-wheel checks. Whole-table selections,
conditional text formats and literal-only replacements remain deferred.

### Reply ancestry and literal display (0.20)

Exposed validated DOC comment relationships without duplicating text or inventing
ancestry after filtering. Added literal-only XLS text sections with distinct
raw/display budget accounting. Both changes passed independent review and public
API/CLI checks. The fixed-denominator fraction investigation remains open because
the consulted evidence did not settle tie-breaking and exact spacing semantics.

### Maintainability pass (0.20.1)

Separated shared output validation from input dispatch without changing the
four validator bodies. Consolidated three duplicated preserved-XLS fixture
oracles, keeping independent expected results and stable family entry points.
No format support or output semantics changed.

### Parser state refactoring (0.20.2)

Extracted RTF group entry/exit and auxiliary-story finalization into private
helpers. Token ordering, Unicode fallback, decoder flushing, suppression and
sink lifetime remain under the same parser state.

Extracted DOC note and comment reference observation from text cleaning into
separate helpers. Their distinct failure policies and source-CP semantics remain
unchanged; observation still precedes field transitions and text filtering.

Both changes are independently reviewable. ODF story/repetition accounting stays
unchanged until a concrete duplication or coupling problem justifies a change.

### Structured adapter contract (0.21)

Expose DOC heading levels without requiring conversion to an intermediate
format. Retain inherited/direct outline semantics, source ownership and bounded
metadata in paragraphs, cells and auxiliary stories. Validate with independent
binary evidence, authored source/readback documents and public API/CLI checks.

Document XLS adapters over sparse cells, explicit merges and retained raw/display
values. Header selection, repeated column labels and DOC heading-path stacks are
consumer policies, with isolated context for cells and auxiliary stories.

### Local-corpus compatibility (0.21.1)

Handle a single terminal RTF NUL and reserved DOC textbox sentinel coordinates
without weakening live text boundaries. Reproduce both with original synthetic
regressions; private corpus files, names and content are not repository fixtures.
Retain the default record budget and document explicit consumer resource profiles
for large, structurally dense documents.

### Text-document heading contract (0.22)

Extend the shared paragraph model to RTF and ODT while preserving text, table
ownership and story-local context. Validate explicit outline controls separately
from RTF style-name inference; preserve independent reference-reader evidence
when a writer loses source metadata. Document the complete Python/JSON output
contract and omission rules in [OUTPUT_FORMAT.md](OUTPUT_FORMAT.md).

## Post-0.22 output fidelity

The ordered work is recorded in [NEXT_STEPS.md](NEXT_STEPS.md), with validation
in [TESTING.md](TESTING.md). This development iteration adds supported visibility
filtering, optional display normalization, diagnostic codes, ODF templates,
individual note bodies and bounded XLS fraction formats. It also verifies deep
serialization and process isolation. Remaining format coverage is tracked in
[EXTRACTION_GAPS.md](EXTRACTION_GAPS.md); a completed iteration does not mean
universal rendering parity.
