# ODF sheet and slide visibility style ownership

## Problem and contract

The sheet/slide hidden-metadata lookup formerly flattened all style definitions,
including definitions in embedded documents and automatic styles from another XML
part. A same-named foreign style could change a host sheet or slide's hidden flag.
Text was retained, but consumers filtering hidden content could make the wrong
choice based on this metadata.

The lookup now reuses the existing per-element style scopes: common styles and
family defaults, XML-local automatic styles, and isolated embedded-document
scopes. Families are part of each key. A local automatic style takes precedence;
parent references resolve common styles, including a common style with the same
name as the initial automatic style. A resolved chain without a property uses the
same-family default, as does an element without a style name. An explicit visible
property takes precedence over a hidden parent or default.

Missing, duplicate or cyclic definitions do not justify marking content hidden.
They leave the flag false with `odf_sheet_slide_visibility_style_unresolved`.
An unresolved chain does not fall through to a hidden default. Existing depth
limits still raise; this change adds no document-wide style index or output copy.
Hidden sheet/slide text is retained under the existing consumer-policy contract.

## Evidence and validation

The normative reference is [OpenDocument 1.3 Part 3](https://docs.oasis-open.org/office/OpenDocument/v1.3/os/part3-schema/OpenDocument-v1.3-os-part3-schema.html),
particularly sections 3.15, 16.2 and 19.510. Parent styles must be common styles;
absence of a parent uses the default style of the same family. Embedded documents
have their own style scope.

Original ODS/ODP XML regressions in `test_odf_visibility_scope.py` cover foreign
style collisions in both visibility directions, isolated defaults, XML-part
ownership, same-name automatic/common inheritance, invalid parent chains,
duplicate styles/defaults, explicit visibility and retained host text. The six
initial embedded-style cases failed on 0.25. Independent review also exercised
unresolved chains, family mismatches and unstyled elements.

The pre-existing inheritance-depth fixture now uses common parents in styles.xml;
its former automatic-to-automatic chain was outside the normative parent model.
Its depth-boundary and missing-parent checks remain in place.
