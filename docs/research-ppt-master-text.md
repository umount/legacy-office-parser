# PPT inherited ordinary master text

Implemented on 2026-10-21. Only `ppt.py` and
`tests/test_ppt_master_text.py` change executable behavior. Models and runtime
dependencies are unchanged. This note supersedes the previous master-text
exclusion in the WordArt research note for the specific path described here.

## Primary sources and decisions

- [MS-PPT 2.4.14.1, MasterListWithTextContainer](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-ppt/18a9bc04-3307-440e-bbc2-efcb75ee923d)
  identifies the master list as record 4080, instance 1.
  [MasterPersistAtom](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-ppt/ffcca362-b860-4a3d-900e-5c03f02c1775)
  connects master IDs to persist IDs, whose objects may be MainMasterContainer
  (1016) or SlideContainer (1006, a title master). We use the existing latest-edit
  directory and the current document's list, never a scan of historic records.
- [SlideAtom](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-ppt/57e11e6c-e550-4c43-80b6-72731eee8abd)
  puts the master reference at payload offset 12 and slide flags at offset 20.
  [SlideFlags](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-ppt/a840eba8-ed03-47a0-a0c9-769236e21a0b)
  distinguishes inherited objects (bit 0), scheme (bit 1), and background (bit 2).
  Only the objects bit enables this text path. A title master's own objects bit
  controls further inheritance. Main masters have no parent. A disabled edge
  does not resolve or parse the target.
- [OfficeArtClientData](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-ppt/ac3b454d-b5ea-4da8-a57c-32fc08ed332a)
  carries [PlaceholderAtom](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-ppt/5a37fba1-1e70-45d8-bda4-315730bd3c54).
  Master title/body shapes are template content; date/footer/number shapes need
  slide-specific field evaluation. We conservatively exclude every master shape
  carrying this atom, including position -1: placementId can still describe a
  conditional field. This intentionally may omit unusual ordinary shapes with
  residual placeholder metadata. Metadata is inspected before text regardless
  of record ordering, so template strings and their WordArt forms do not leak.
- [OfficeArtFSP](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-odraw/8a7e7be3-0582-4461-9400-29d7eda8497d)
  identifies deleted and background shapes. Both are excluded. An excluded group
  also excludes its children.
  [Group Shape Boolean Properties](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-odraw/a0ae6aa5-16e4-4550-87a2-b8ca180c7fd7)
  define explicit fHidden and its use bit (0x00020002 together).
  [Shape Boolean Properties](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-odraw/aff4b132-455c-40bf-9639-e48a13e1cd5c)
  define explicit background and its use bit (0x00010001). Direct FOPT and
  TertiaryFOPT declarations are checked before decoding. No geometry is rendered.
- [Apache POI DrawMasterSheet](https://github.com/apache/poi/blob/trunk/poi/src/main/java/org/apache/poi/sl/draw/DrawMasterSheet.java)
  independently corroborates that ordinary master graphics and conditional
  placeholders use different display decisions. No implementation code copied.

## Content and bounds

Ordinary native text and stored WordArt are appended to the corresponding slide's
body, after its own text, in master drawing order. Inherited title-kind artwork
is not promoted to the slide title. For a title master, its own artwork precedes
its inherited parent artwork in extraction order; this is not a layout order.
Equal strings on separate shapes and slides remain distinct. The existing
same-shape WordArt/native duplicate policy remains unchanged.

Each reached master is decoded once per parse; only its own blocks and parent
edge are cached. Every followed edge consumes the record/work budget, even on a
cache hit. Cycles fail closed and inheritance-chain length uses max_depth.
Record nesting, property entries, decoded code units, master-list length and
final repeated output retain the existing budgets. Reused master text and output
separators count on every emitted slide. No larger limits were introduced.

Unresolved enabled references, wrong master types, malformed live metadata,
missing/duplicate master atoms and main-master parent references fail closed.
Unused master bodies and disabled edges are not parsed. The document's master
list itself remains bounded and duplicate IDs/lists are rejected.

Runtime remains passive: no macros, commands, external fetches, archive expansion,
embedded-object opening or LibreOffice dependency. Development used only authored
synthetic data, existing tests, and read-only primary sources.

## Original real fixture and independent expectation

LibreOffice 7.4.7.2 authored a new three-slide Impress document. Default master
placeholders were retained; one ordinary TextShape was added to that master:
`MASTER NOTICE / Привет 世界`. Slides were stripped of their default shapes and
received ordinary TextShapes `Slide 1`, `Slide 2`, `Slide 3`. Their
IsBackgroundObjectsVisible properties were true, false, true. The file was saved
using the MS PowerPoint 97 filter, closed and independently reopened via UNO.

UNO reported the master notice as a CustomShape with IsPresentationObject=false,
and title, outline, date, footer and number shapes with IsPresentationObject=true.
The three object-visibility values survived. The authored false background flag
on slide 1 did not survive export (all three read back true), so the independent
fixture does not establish that combination; wire fixtures test all relevant
flag combinations against the spec.

The literal expected slide bodies are:

```text
Slide 1\nMASTER NOTICE / Привет 世界
Slide 2
Slide 3\nMASTER NOTICE / Привет 世界
```

The parser returns these values, empty titles/notes and no warnings. Disabling
only master_text produces the three local labels without the notice, proving
that the fixture exercises newly recovered content. The test reads the original
unmodified CFB from `tests/fixtures/ppt_master/master_objects.ppt`, with an SHA-256 assertion. No office application is
needed to run it. File size: 462848 bytes. SHA-256:
`7d932d6c1ab3ab1bde31acdfa7ff06832641aa910beceff8c91e5e34f4922077`.

Independent evidence remains in `/tmp/ppt-master-evidence/master-original.ppt`
and `/tmp/ppt-master-evidence/uno-readback.json`. A trial per-page SVG export
contained only local text and was not used as a visual oracle. This validation
establishes stored text, placeholder identity and inheritance flags, not visual
fidelity or Microsoft PowerPoint interoperability.

To reproduce equivalent authored content, connect system Python's `uno` module
to an isolated headless soffice using a unique pipe and UserInstallation profile.
Create `private:factory/simpress`, use getMasterPages().getByIndex(0), and add a
`com.sun.star.drawing.TextShape` with the notice, Position=(1500,14000),
Size=(22000,1800). On three draw pages, remove existing shapes, setMasterPage to
that master, set IsBackgroundObjectsVisible=(true,false,true), and add one
TextShape with each local label at (1500,2500), size (22000,1800). Export via
storeToURL with FilterName='MS PowerPoint 97'. Reopen read-only with macros never
executed and document updates disabled. Inspect each page's master shapes using
String and IsPresentationObject, and inspect IsBackgroundObjectsVisible. Binary
hashes can vary with generated previews/timestamps. Do not use private documents.

## Limitations

This adds ordinary master artwork only. Master placeholders, conditional
headers/footers/dates/slide-number fields, notes/handout masters and extension-only
content remain outside scope. Active master ProgTags warn without string scanning.
No arbitrary drawing-group property defaults, hspMaster style inheritance,
animations, script-anchor behavior, clipping, occlusion, transparent text or
page layout are evaluated. Explicit direct hidden/deleted/background metadata is
filtered, but the result is a content extraction, not a claim that every retained
character is visually exposed in a rendered slideshow. Contradictory explicit
visibility declarations conservatively exclude the shape.

## Validation

Focused suite:

```sh
.venv/bin/python -m pytest tests/test_ppt.py tests/test_ppt_wordart.py tests/test_ppt_extensions.py tests/test_ppt_master_text.py -q
.venv/bin/ruff check src/legacy_office_parser/ppt.py tests/test_ppt_master_text.py
```

Additional existing regressions: fixture corpus, extended fixture corpus,
document reference, security side effects and API tests (116 passed).
