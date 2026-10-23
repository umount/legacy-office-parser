# PPT (PowerPoint 97–2003)

## Supported

- Current User → UserEdit → persist directory resolves active slides and notes.
  Empty slides and original ordering are preserved; stale edits are not indexed.
- Native slide/shape/outline text, notes, comments, supported master text,
  explicit WordArt and verified stored footer/date fields.
- Ordinary notes-master artwork follows the notes page's own inheritance flag.
  Template prompts are excluded; a missing optional drawing is empty.
- Inline footer/fixed-date fields use slide settings or document defaults;
  an explicit local override never borrows missing strings from the default.
  Notes use their own header/footer/date settings. Repeated field copies share
  the text limit, and substituted values are not appended a second time.
- Optional comment strings and absent notes/footer values do not block slide
  text. Source relationships and shared record/text limits still apply.

## Limits and remaining work

Text in unsupported extensions, embedded documents,
images, ink, layout and generated field values are outside current coverage.
An embedded OLE document can contain pages/cells outside its displayed preview.
Its complete contents are not merged into slide text. A future embedded-content
model must preserve that distinction and share parsing/decompression budgets.
A converted presentation is not proof of ownership for an unknown record.
The `metroBlob` alternate DrawingML representation is deliberately ignored;
missing native text does not make that blob authoritative.

## References

- [MS-PPT](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-ppt/): active edit/persist structure and slide/notes ownership.
- [DocumentContainer](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-ppt/6254c4d1-5217-4e16-b20d-c04ddcce31c9): optional lists.
- [SlideAtom](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-ppt/57e11e6c-e550-4c43-80b6-72731eee8abd): notes/master references.
- [metroBlob](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-odraw/0505b55f-f58a-4166-b574-83785d1035c1): ignore the alternate representation.

- [NotesAtom](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-ppt/9bb3e352-1014-477b-b286-cd43127c3b74): notes ownership and inheritance flags.
- [FooterMCAtom](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-ppt/5a2fa1e2-bc5f-450b-89d0-b372a811313a): local/document field sources.

Tests are in `tests/test_ppt*.py`; fixture builders retain original expected
content. Unsupported content diagnostics are not an exhaustive inventory of all
unvisited objects. See [output contract](OUTPUT_FORMAT.md#slides-and-slide-comments).
