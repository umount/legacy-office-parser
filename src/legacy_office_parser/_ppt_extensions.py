"""Conservative classification of metadata-only slide programmable tags.

MS-PPT 2.5.19–24 and 2.8; proof and deliberately narrow scope are documented in
docs/PPT.md. This module never extracts extension text.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .ppt import _Parser, _Record

# Parent-specific types: a familiar record number in another context is unknown.
_CHILDREN = {
    5003: {12011, 11008, 61764, 11010},  # PP10 slide binary data only
    61764: {61735, 61757, 61761, 61733, 61764},  # ExtTimeNode
    61757: {61762},  # TimePropertyList4TimeNode
    61733: {61736, 61756},  # TimeCondition
    61756: {11009},  # ClientVisualElement (page target only)
    11010: set(),  # Only an EMPTY BuildList is classified.
}
# (recVer, permitted recInstance, exact payload size; None means container)
_HEADERS = {
    12011: (0, {0}, 8),  # SlideTime10Atom
    11008: (0, {0}, 4),  # HashCode10Atom
    11010: (15, {0}, None),
    61764: (15, {1}, None),
    61735: (0, {0}, 32),  # TimeNodeAtom
    61757: (15, {0}, None),
    61762: (0, {20}, 5),  # ONLY TimeEffectNodeType (not general TimeVariant)
    61761: (0, {0}, 20),  # TimeSequenceDataAtom
    61733: (15, set(range(6)), None),
    61736: (0, {0}, 16),  # TimeConditionAtom
    61756: (15, {0}, None),
    11009: (0, {0}, 4),  # VisualPageAtom
}
_REQUIRED = {61764: {61735}, 61733: {61736}, 61756: {11009}}


def _timing_metadata(parser: _Parser, blob: _Record) -> bool:
    # Explicit iterator stack: O(depth) auxiliary state, shared depth/record
    # budgets, no recursion and no copying or decoding unknown payloads.
    stack = [(blob, iter(parser.children(blob)), set())]
    while stack:
        parent, children, seen = stack[-1]
        rec = next(children, None)
        if rec is None:
            if not _REQUIRED.get(parent.type, set()) <= seen:
                return False
            stack.pop()
            continue
        if rec.type not in _CHILDREN[parent.type]:
            return False
        # Only child time nodes and time conditions are arrays in this subset.
        if rec.type in seen and not (parent.type == 61764 and rec.type in (61764, 61733)):
            return False
        seen.add(rec.type)
        version, instances, size = _HEADERS[rec.type]
        if rec.version != version or rec.instance not in instances:
            return False
        if size is None:
            stack.append((rec, iter(parser.children(rec)), set()))
            continue
        parser.size(rec, size, exact=True)
        if rec.type == 61762:
            if parser.data[rec.start] != 1 or not 1 <= parser.u32(rec, 1) <= 9:
                return False
        elif rec.type == 11009 and parser.u32(rec) != 1:
            return False
    return True


def slide_metadata_only(parser: _Parser, tags: _Record) -> bool:
    """True only when every tag is the explicitly understood metadata subset.

    Unknown formats keep the omission warning. Malformed traversed record bounds
    or known fixed lengths fail closed through the ordinary parser checks.
    This is a text-content classifier, not an animation semantic validator.
    """
    if tags.version != 15 or tags.instance != 0:
        return False
    seen_ppt10 = False
    for tag in parser.children(tags):
        if tag.type != 5002 or tag.version != 15 or tag.instance != 0 or seen_ppt10:
            return False
        pair = iter(parser.children(tag))
        name = next(pair, None)
        if (name is None or name.type != 4026 or name.version != 0 or name.instance != 0
                or name.end - name.start != 16
                or parser.data[name.start:name.end] != '___PPT10'.encode('utf-16-le')):
            return False
        blob = next(pair, None)
        if (blob is None or blob.type != 5003 or blob.version != 0 or blob.instance != 0
                or next(pair, None) is not None):
            return False
        seen_ppt10 = True
        if not _timing_metadata(parser, blob):
            return False
    return True
