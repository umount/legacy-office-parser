"""Select shape representations by presence, never by extracted text.

RTF 1.9.1: shpinst contains the modern shape; shprslt contains the Word 6/95
representation of its owner. An empty modern representation remains authoritative.
The structural scan retains only group state and selected destination positions.
"""
from dataclasses import dataclass

from .errors import InvalidDocumentError, LimitExceededError


@dataclass
class _Shape:
    native: bool = False
    result: int | None = None
    result_count: int = 0


@dataclass
class _Group:
    first: bool = True
    destination: str = ''
    owner: _Shape | None = None
    in_result: bool = False
    opaque: bool = False
    starred: bool = False
    container: bool = False
    uc: int = 1
    upr: bool = False
    children: int = 0


def shape_fallbacks(tokens, max_depth: int, opaque_destinations: set[str],
                    story_destinations: set[str]) -> set[int]:
    groups = []
    selected = set()
    fallback = 0
    native_destinations = {'shp', 'shpgrp', 'shpinst', 'shptxt'}
    known_starred = native_destinations | story_destinations | {'shprslt', 'ud', 'fldrslt', 'nesttableprops'}
    for position, (kind, value, number) in enumerate(tokens):
        if kind == 'open':
            fallback = 0
            if len(groups) >= max_depth:
                raise LimitExceededError('RTF group depth limit exceeded')
            parent = groups[-1] if groups else None
            if parent:
                parent.children += 1
            groups.append(_Group(
                owner=parent.owner if parent else None,
                in_result=parent.in_result if parent else False,
                opaque=bool(parent and (parent.opaque or parent.upr and parent.children != 2)),
                container=parent.container if parent else False,
                uc=parent.uc if parent else 1))
        elif kind == 'close':
            fallback = 0
            if not groups:
                raise InvalidDocumentError('Unbalanced RTF closing group')
            group = groups.pop()
            if (group.destination in {'shp', 'shpgrp'} and not group.in_result
                    and not group.opaque and not group.owner.native and group.owner.result_count == 1):
                selected.add(group.owner.result)
        elif groups:
            group = groups[-1]
            if fallback:
                fallback -= min(fallback, len(value)) if kind == 'bytes' else 1
                if kind == 'bytes':
                    group.first = False
                continue
            if kind == 'symbol' and value == '*':
                group.starred = True
                continue
            if kind == 'word':
                destination = group.first or group.starred or value in opaque_destinations | native_destinations | {'shprslt'}
                if destination:
                    if (value in opaque_destinations
                            or group.owner is not None and value in story_destinations
                            or group.starred and value not in known_starred):
                        group.opaque = True
                    if not group.opaque:
                        owner = group.owner
                        if value in {'shp', 'shpgrp'} and not group.in_result:
                            if owner is not None:
                                owner.native = True
                            group.owner = _Shape()
                            group.destination = value
                            group.container = True
                        elif value in {'shpinst', 'shptxt'} and owner is not None and not group.in_result:
                            owner.native = True
                            group.container = value != 'shptxt'
                        elif value == 'shprslt':
                            group.in_result = True
                            if (owner is not None and len(groups) > 1
                                    and groups[-2].destination in {'shp', 'shpgrp'}
                                    and groups[-2].owner is owner and not groups[-2].in_result
                                    and number is None):
                                owner.result_count += 1
                                owner.result = position
                if not group.opaque and not group.container:
                    if value == 'uc' and number is not None and number >= 0:
                        group.uc = number
                    elif value == 'u':
                        fallback = group.uc
                    elif value == 'upr':
                        group.upr, group.children = True, 0
            group.first = group.starred = False
    return selected
