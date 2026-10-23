"""Notes-master content from the live DocumentAtom persist reference.

MS-PPT 2.4.2, 2.5.6 and 2.5.12. The caller follows this optional edge only
for an active notes slide whose NotesAtom.slideFlags.fMasterObjects is set.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from .diagnostics import diagnostic_warning
from .errors import InvalidDocumentError

if TYPE_CHECKING:
    from .ppt import _Parser


def notes_master(parser: _Parser) -> tuple[list[tuple[int, str]], set[int]]:
    """Return cached ordinary artwork and visible field placements, not prompts.

    Initialize notes_master_id=0 and notes_master_cache=None on the parser.
    Returned containers are shared: callers must not mutate them. Decoding uses
    the parser's text budget; the caller charges repeated emitted output as usual.
    """
    if not parser.notes_master_id:
        return [], set()
    if parser.notes_master_id in parser.notes_persist_ids:
        raise InvalidDocumentError('PPT notes master aliases a notes slide')
    parser.charge()
    if parser.notes_master_cache is None:
        master = parser.resolve(parser.notes_master_id, 1008)
        if master.instance != 0:
            raise InvalidDocumentError('invalid PPT notes master container instance')
        children = list(parser.children(master))
        atoms = [rec for rec in children if rec.type == 1009]
        drawings = [rec for rec in children if rec.type == 1036]
        if len(atoms) != 1 or len(drawings) > 1:
            raise InvalidDocumentError('missing or duplicate PPT notes master atom/drawing')
        atom = atoms[0]
        parser.size(atom, 8, exact=True)
        if atom.version != 1 or atom.instance != 0:
            raise InvalidDocumentError('invalid PPT notes master atom header')
        # Some writers store a master ID in slideIdRef. This object is already
        # owned by DocumentAtom; neither that value nor its flags is a new edge.
        fields: set[int] = set()
        # The master is a separate text owner; slide-local field substitution
        # and placement bookkeeping must not influence its cached artwork.
        saved = (parser.collect_master_fields, parser.local_fields,
                 parser.inline_values, parser.inline_fields_done)
        parser.collect_master_fields = fields
        parser.local_fields = None
        parser.inline_values = {}
        parser.inline_fields_done = set()
        try:
            blocks = [(1, value) for _, value in
                      (parser.drawing_text(drawings[0], [], inherited=True) if drawings else []) if value]
        finally:
            (parser.collect_master_fields, parser.local_fields,
             parser.inline_values, parser.inline_fields_done) = saved
        for rec in children:
            if rec.type == 5000:
                parser.warn(diagnostic_warning(
                    'ppt_master_extension_records_are_not_extracted_extension_only',
                    'PPT master extension records are not extracted; extension-only content may be omitted.'))
        parser.notes_master_cache = blocks, fields
    blocks, fields = parser.notes_master_cache
    parser.charge(len(blocks))  # Charge before callers iterate/extend cached text.
    return blocks, fields
