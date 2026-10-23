# Scope and alternatives

One Python API reads DOC, XLS, PPT, RTF and OpenDocument directly, without an
office runtime. It retains structures useful to LLMs: nested tables, sparse
coordinates, active slides, cached values and source-owned auxiliary stories.

LibreOffice is a development comparator. On specific original fixtures the
parser matches verified text/structure, and sometimes retains source information
lost during conversion (for example DOC comment ranges). This is not universal
rendering or extraction parity. Apache OpenOffice has not been separately tested.

The initial review of sharepoint-to-text found heuristic DOC table/text extraction
and PPT traversal without current-persist ownership. WordCraft informed DOC
format research; xlrd informed BIFF records/strings. These were scoped inspections,
not an exhaustive benchmark or ranking. Consulted versions, licenses and any
adaptation attribution remain in [THIRD_PARTY.md](../THIRD_PARTY.md).

Current support and limitations: [DOC](DOC.md), [XLS](XLS.md), [PPT](PPT.md),
[RTF](RTF.md), [ODT](ODT.md), [ODS](ODS.md), [ODP](ODP.md).
