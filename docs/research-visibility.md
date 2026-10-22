# Stored text visibility

The post-0.22 readers extend supported stored visibility without executing
conditions, accepting/rejecting revision histories, or rendering pages.

## RTF

Paragraph and character styles retain explicit hidden/deleted properties,
resolve same-family inheritance iteratively, and distinguish absent properties
from explicit false. Direct formatting, group restoration, additive character
styles and `plain` resets have original regression cases. Missing bases and
cycles use available properties with diagnostics; table/section styles and
`webhidden` remain outside this subset.

Suppressed text does not erase table positions and structural boundaries. Field
instructions remain suppressed. Stories preserve applicable inherited visibility;
this is not a blanket guarantee that all Word visibility rules are implemented.

Reference: [RTF 1.9.1 specification](https://officeprotocoldoc.z19.web.core.windows.net/files/Archive_References/%5BMSFT-RTF%5D.pdf),
style sheet, additive styles and character properties.

## OpenDocument

Paragraph/text style visibility uses scoped common, automatic and default styles.
Embedded text documents have independent scopes. Explicit `text:display` values,
stored hidden-paragraph field states and hidden sections are checked before
collecting text or detached stories. Explicit visible overrides remain effective.
ODS/ODP traversal also excludes supported hidden sections. ODS retained typed
values must not resurrect a deliberately empty display projection.

Unknown conditional expressions are not evaluated. Missing/duplicate styles,
cycles and unsupported conditions are diagnosed; proven properties are used
without claiming a complete rendered view. Style inheritance and expanded
content remain bounded. Tracked-deletion payloads are not visited as ordinary
content; this does not reconstruct arbitrary revision histories.

Reference: [ODF 1.3 Part 3](https://docs.oasis-open.org/office/OpenDocument/v1.3/os/part3-schema/OpenDocument-v1.3-os-part3-schema.html),
sections 7.7.11, 16.2 and the `text:display`/`text:is-hidden` definitions.

## Validation boundaries

Original synthetic tests cover styles, overrides, hidden cells and stories,
cyclic/missing inheritance, limits, and stored visibility. Conditional evaluation,
complete historical revision views and removal of separately retained DOC note
bodies merely because their references are hidden remain unsupported.
