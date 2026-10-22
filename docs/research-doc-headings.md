# DOC heading semantics and independent fixture evidence

Research and original fixture authored on 2026-10-22. No private documents or
production decoder internals were used to construct the source document.

## Primary sources and implementation consequences

[MS-DOC §2.6.2 Paragraph Properties](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/484822ee-a9d9-4af4-8423-29fda67a6a58)
specifies POutLvl (0x2640): 0–8 are outline levels, 9 is body. It is ignored
when the current paragraph istd is 1–9. PIstd sets a built-in heading's outline
to istd minus one. Applying another style resets the relevant formatting;
outline handling cannot simply retain a previous direct override. Invalid
style references temporarily apply default formatting and must be repaired
by a subsequent style selection.

PIncLvl (0x2602) is signed. For istd 1–9 it changes the style index, clamped to
1–9. Otherwise it changes outline, clamped to 0–9, except body level 9 is
unchanged. PIstdPermute is a conditional style replacement. Unsupported
increment/permutation operations must not silently produce guessed levels.
List level PIlvl is distinct from outline.

[STSH §2.9.271](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/c8ee0f39-02c3-4caa-b27a-6a97600130fe)
reserves fixed style indices. Slots 1–9 correspond to built-in sti 1–9.
A synthetic custom style with sti=0xFFE at index 1 contradicts this requirement;
use index 15 or later for a custom paragraph style test. The POutLvl exception
checks current istd, not an ancestor index and not a user-visible name.

[StdfBase §2.9.260](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/df0f4654-071d-442f-8563-752d7e0285ef)
defines sti as language-independent built-in identity, with 0xFFE for custom
styles. Name-based heading recognition is unsuitable. A custom style based on
a built-in heading retains its own index and can explicitly set body outline.

[Determining Properties of a Style §2.4.6.5](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/9258b41c-ff0a-4c96-a3a9-610664dabbeb)
requires following istdBase and obtaining the style's property arrays.
Inheritance must use bounded style resolution, not promote every descendant
unconditionally. Preserve the ancestor's stored POutLvl operand, even when that
operand would be ignored if the ancestor itself were the selected paragraph
style. The built-in exception applies to the paragraph's current istd, not each
ancestor visited during property collection.

For example, custom istd=15 based on built-in istd=2 inherits an explicit
POutLvl=4 from that ancestor as heading level 5, while a paragraph selecting
istd=2 directly remains heading level 2. If no ancestor supplies POutLvl, the
custom paragraph defaults to body; the parent's fixed index alone does not
supply an inherited outline operand. A local or direct body operand likewise
suppresses an inherited outline for that custom paragraph. These are semantic
consequences of collecting style Prls separately from applying the selected
paragraph's fixed-index rule. They need synthetic regressions distinct from the
authored fixture, whose parent explicitly contains POutLvl=0.
[Applying Properties §2.4.6](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/4e918665-c4da-41d8-aed5-615c2e96c216)
requires the specified application order, with operation-specific exceptions
to the usual last-property-wins behavior.

[Prm0](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/35226a0b-9038-4427-83c2-3830a8554267)
also maps compact isprm 0x04 to PIncLvl and 0x78 to POutLvl. Reviewing only PAPX
SPRM bytes misses piece-level overrides. These compact forms need separate
runtime unit tests; this fixture does not claim to exercise them.

## Original authored fixture

`tests/fixtures/doc_headings/fixture.py` generates a deterministic, minimal
`authored.docx`. LibreOffice 7.4.7.2 (40 Build 2) exported `authored.doc` using
MS Word 97, then reopened that binary into `readback/authored.docx` using Office
Open XML Text. Both conversions used a fresh external temporary profile.

The content covers built-in Heading 1 and Heading 2, Normal body text, a custom
style based on Heading 1, that same custom style with direct body override,
a separate custom child with its own body outline, Normal with direct outline
level 3, a table-cell Heading 2, and a header-story Heading 2.

The independent helper imports no production parser. Its literal STSH/CLX/PAPX
probe establishes in the exported DOC:

- Heading slots 1 and 2 have matching sti and POutLvl values 0 and 1.
- `Research inherited` occupies slot 20, sti=0xFFE, istdBase=1, with no local
  POutLvl. The inherited-heading paragraph also has no direct POutLvl.
- The direct-body paragraph selects the same slot 20 and carries POutLvl=9.
- `Research body child` occupies slot 21, istdBase=1, with local POutLvl=9.
- Direct outline level 3 uses Normal (istd=0) with POutLvl=2.
- The cell and header paragraphs both select istd=2; the cell has PFInTable=1.

The helper is deliberately fixture-specific: ASCII CPs, direct non-huge PAPX,
named nonempty paragraphs. It does not validate every unused FKP run, empty
terminal paragraph, or general MS-DOC input. Production tests separately check
that the header is actually in story_blocks and that Document.text includes
each specimen exactly once. Merely preserving its legacy string does not prove
heading metadata survived.

## LibreOffice discrepancy and scope limits

The saved DOC readback agrees with eight of nine intended outline values.
For `Inherited heading specimen`, LibreOffice writes outlineLvl=9 into the custom
style on readback, losing the inherited heading. The stored DOC still has the
explicit parent chain and Heading 1's POutLvl=0. The tests record this loss
explicitly; the readback is not positive external confirmation of that case.
A newer LibreOffice may preserve it; the optional live oracle accepts either
outcome for that one case while strictly checking the other eight.

This specimen does not prove Word interoperability, every story type, built-in
heading/direct-body conflict behavior, absent styles, invalid outline operands,
style changes mid-SPRM sequence, compact PRMs, PIncLvl, permutations, or resource
limits. Those require targeted unit tests and independent implementation review.
No runtime Office execution or network access is introduced.

## Reproduction

From the repository root:

```sh
.venv/bin/python tests/fixtures/doc_headings/fixture.py
libreoffice -env:UserInstallation=file:///tmp/doc-headings-oracle-profile \
  --headless --convert-to 'doc:MS Word 97' \
  --outdir tests/fixtures/doc_headings tests/fixtures/doc_headings/authored.docx
libreoffice -env:UserInstallation=file:///tmp/doc-headings-oracle-profile \
  --headless --convert-to 'docx:Office Open XML Text' \
  --outdir tests/fixtures/doc_headings/readback tests/fixtures/doc_headings/authored.doc
.venv/bin/python -m pytest -q tests/test_doc_headings_ole.py
OFFICE_CORPUS_LIBREOFFICE=1 .venv/bin/python -m pytest -q \
  tests/test_doc_headings_ole.py -k live
```

The DOC and readback OOXML are reader-produced artifacts, not byte-deterministic
outputs across LibreOffice versions. The source ZIP is deterministic. Temporary
profiles, lock files and Python caches are not fixture deliverables.
