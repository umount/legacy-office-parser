# PPT stored footer and fixed-date text

Stored static slide fields extend the active master-text path. Field values
are preserved without clock access or field evaluation.

## Primary-source contract

[MS-PPT 2.4.15.1](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-ppt/c1ff52eb-b70a-4de3-a033-85eefc7a25a8)
defines document-level presentation-slide settings: RT_HeadersFooters (4057),
version 15, instance 3. Instance 4 is the separate notes default and is not a
presentation-slide text source.
[2.5.16](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-ppt/0104cfcf-3781-4fbb-954d-5cd43e2d4e35)
defines the per-slide container (same type/version, instance 0), also permitted
on masters. A slide-local container overrides the document default as a whole;
missing local strings do not borrow from the document default. Apache POI's
[HeadersFooters constructor](https://github.com/apache/poi/blob/trunk/poi-scratchpad/src/main/java/org/apache/poi/hslf/model/HeadersFooters.java)
independently corroborates local-container-first, document-default-second
selection. It also distinguishes newer shape-based footer storage. No POI code
was copied. Master-local settings are not assumed to be ordinary-slide defaults.

[HeadersFootersAtom, 2.4.15.2](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-ppt/5ba5b716-138d-4643-9dbd-fa1382d25082)
is record 4058, version/instance 0, four-byte payload: a two-byte date format ID
followed by two-byte flags. Bits 0–5 are date-visible, current-date,
user-date, slide-number, header and footer. Reserved bits are ignored. Format ID
is irrelevant to fixed stored text and is not evaluated.

[UserDateAtom, 2.4.15.3](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-ppt/59b1690f-1aea-4b12-846f-3a1bec342425)
is CString (4026), instance 0, an even UTF-16 byte count no greater than 510.
[FooterAtom, 2.4.15.5](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-ppt/be368875-33e9-490d-b832-954eb800a240)
is CString, instance 2, with an even UTF-16 payload. These are actual stored
strings. The implementation extracts footer text only with bit 5 enabled, and
fixed-date text only with bits 0 and 2 enabled and bit 1 clear. Both optional
records may be absent; an absent static value is empty, not an unsupported field.
This matters for otherwise empty LibreOffice decks that enable default flags.
Header text is not a presentation-slide source.

[PlaceholderAtom, 2.7.8](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-ppt/5a37fba1-1e70-45d8-bda4-315730bd3c54)
identifies master date, slide-number and footer fields by placement IDs 7, 8 and 9.
A matching placeholder must be found on the already validated active master
object-inheritance path. Deleted, background and explicitly hidden shapes and
excluded groups do not provide placement evidence. This is a conservative
eligibility rule, not a full PowerPoint rendering implementation. Disabled master
objects, missing placement, or other unresolved visibility cause a warning and
no synthesized field text.

[DocumentAtom, 2.4.2](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-ppt/121f2728-3497-4a0a-829e-6f416fee2ee6)
provides fOmitTitlePlace at payload offset 37. It suppresses this inherited field
path on slides whose layout is SL_TitleSlide (0), as defined by
[SlideLayoutType](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-ppt/df8f3d7b-db67-47dc-8c89-20f5cbbf0fa9).
It does not remove the slide's own title/body.

## No field evaluation

[SlideNumberMCAtom](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-ppt/3f615199-95ec-48c0-acb4-dd98f0f29560)
contains a metacharacter position, not a stored numeric result. Likewise,
[DateTimeMCAtom](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-ppt/668ab84b-f0b2-4496-af11-b9d1b04e840a)
requires current datetime, while
[GenericDateMCAtom](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-ppt/a212a377-6044-4ec2-a594-8c59be237125)
uses the selected datetime option. No time, locale formatting, slide-number
calculation or metacharacter substitution is performed. Active automatic dates,
ambiguous date flags and active slide-number fields warn. Explicit ordinary text
containing a date or number continues through the existing native text path.

[FooterMCAtom](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-ppt/5a2fa1e2-bc5f-450b-89d0-b372a811313a)
identifies replacement positions in native text. This change does not perform
those replacements. Native text blocks containing date/header/footer/number
metacharacters are retained as stored, with an explicit warning that markers
are unevaluated. This may retain placeholder characters; it must not be presented
as an evaluated field value.

Local field placeholders, matching inline field markers, or
[RoundTripHFPlaceholder12Atom metadata](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-ppt/92bce4f0-921c-4b5b-92d3-7ade03646250)
prevent merging a legacy string into a potentially existing local representation.
The stored native text survives, and an active legacy merge attempt warns.
Round-trip metadata conservatively blocks all legacy field merges on that slide;
no newer-version shape/field visibility evaluator is claimed. Master-only active
header/footer settings without a document/slide source warn instead of being
silently interpreted as defaults.

## Output, bounds and duplication

Stored date then footer are appended as body blocks after ordinary slide/master
text. The order is semantic, not page layout. Each field appears at most once per
slide, even if master inheritance exposes multiple matching placeholder shapes.
Equal values in different fields or ordinary body shapes are not deduplicated.

Only the current document list/latest persist graph supplies slides and masters.
Settings cache record descriptors, not expanded strings. Reusing cached settings
and visiting master inheritance edges consume the record/work budget. Active
strings use the strict shared UTF-16 decoder and text budget on every slide;
final output and separators retain the existing output limit. Inactive strings
are not decoded. Duplicate containers/flags/strings, bad record lengths, odd
UTF-16 lengths and invalid active UTF-16 fail closed. All record scans retain
existing parent/depth bounds. No budgets were raised.

## Original fixture and independent expectation

`tests/fixtures/ppt_fields/static_fields.ppt` is an original, unmodified 462848-byte
CFB authored through LibreOffice 7.4.7.2, using the MS PowerPoint 97 export filter.
SHA-256: `ebd05d26ee50d3d5160820d2b5d8d634ea41bfe1a91b0500b164808a98f53192`.
It contains no private or third-party content. Unlike the earlier master fixture,
it deliberately sets per-slide static footer/date strings.

Three blank-layout draw pages contain ordinary TextShapes `Body 1`, `Body 2`,
`Body 3`. FooterText is `Stored footer / Привет` on slides 1–2 and
`Different footer` on slide 3. DateTimeText is `Fixed date / 2040-06-17` on slides
1–2 and `Another stored date` on slide 3. IsDateTimeFixed is true throughout;
IsFooterVisible and IsDateTimeVisible are true, false, true; IsPageNumberVisible
is false throughout. The default master supplies its date/footer/number shapes.

After saving, a separate read-only UNO reopen with NEVER_EXECUTE and document
updates disabled returned those exact strings and flags. Evidence is at
`/tmp/ppt-fields-evidence/uno-readback.json`. Literal test expectations include the
two stored strings only on slides 1 and 3; slide 2 retains only `Body 2`, despite
its hidden strings remaining in the file. No warning is produced for this
supported case. Disabling static_slide_fields makes the parser return only the
three body labels, proving recovery of previously omitted text.

To regenerate equivalent content, start isolated headless soffice with a unique
UserInstallation profile and UNO pipe. Create private:factory/simpress, remove
existing shapes from three pages, set Layout=20, add each body TextShape at
Position=(1500,2500), Size=(22000,1800), and set the properties above. Export with
FilterName='MS PowerPoint 97', close, then reopen read-only and inspect each page's
FooterText, DateTimeText, IsDateTimeFixed, IsFooterVisible, IsDateTimeVisible and
IsPageNumberVisible. Hashes can vary with generated metadata/previews. Normal
regressions do not require LibreOffice or UNO.

## Validation and remaining scope

Focused regression command:

```sh
.venv/bin/python -m pytest tests/test_ppt.py tests/test_ppt_wordart.py tests/test_ppt_extensions.py tests/test_ppt_master_text.py tests/test_ppt_fields.py -q
.venv/bin/ruff check src/legacy_office_parser/ppt.py tests/test_ppt_fields.py
```

Existing fixture corpus, extended fixture corpus, document reference, security
side effects and API tests also passed (116 tests).

This does not add notes/handout fields, computed numbering, automatic dates,
full inline replacement, modern field interpretation, master-setting precedence,
or layout-based visibility. Warning fallbacks identify unsupported active paths.
It preserves a proven subset of stored strings rather than attempting rendering.
