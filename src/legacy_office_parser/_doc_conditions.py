"""Narrow, bounded conditional visibility on proven structural table partitions."""
from .diagnostics import diagnostic_warning


def row_boundary(identity, direction, first_frame, props, frame, complete=True):
    return (direction != (props.bidi or props.bidi90) or identity != props.identity
            or (complete and identity.default_position and props.identity.default_position
                and first_frame is not None and frame is not None and first_frame != frame))


def matched(flags, row, column, rows, columns, header, ordinal, bands):
    top = bool(flags & 0x20) and (row == 0 or header)
    bottom = bool(flags & 0x40) and row == rows - 1 and not top
    left = bool(flags & 0x80) and column == 0
    right = bool(flags & 0x100) and column == columns - 1 and not left
    result = []
    if not flags & 0x200 and not (top or bottom) and 0x3488 in bands:
        result.append(64 if (ordinal // bands[0x3488]) % 2 == 0 else 128)
    if not flags & 0x400 and not (left or right) and 0x3489 in bands:
        k = column - bool(flags & 0x80)
        result.append(16 if (k // bands[0x3489]) % 2 == 0 else 32)
    if left or right:
        result.append(4 if left else 8)
    if top or bottom:
        result.append(1 if top else 2)
    # Corners are actual first/last rows; repeated header rows aren't corners.
    tl = row == 0 and column == 0 and flags & 0x20 and flags & 0x80
    tr = row == 0 and column == columns - 1 and flags & 0x20 and flags & 0x100 and not tl
    bl = row == rows - 1 and column == 0 and flags & 0x40 and flags & 0x80 and not (tl or tr)
    br = row == rows - 1 and column == columns - 1 and flags & 0x40 and flags & 0x100 and not (tl or tr or bl)
    if tl or tr or bl or br:
        result.append(512 if tl else 256 if tr else 2048 if bl else 1024)
    return result


class _CellEntries(list):
    """Direct paragraphs only; nested tables are independently styled content."""
    __slots__ = ('nested',)

    def __init__(self):
        super().__init__()
        self.nested = False


def empty_cell(cell):
    return (not cell.nested and len(cell) == 1
            and cell[0][0] == cell[0][1])


def cell_ownership(props, cells, vertical=False):
    """Validate merge ownership independently of row widths and cell counts."""
    if len(props.flags) != len(cells):
        return False
    merged = False
    for flag, cell in zip(props.flags, cells):
        if flag & 0x60 and not vertical:
            return False
        horizontal = flag & 3
        if horizontal == 1:
            if not merged or not empty_cell(cell):
                return False
        else:
            merged = horizontal in (2, 3)
    return True


def vertical_row_context(rows, budget):
    """Prove vertical ownership by consecutive equal rendered edge intervals.

    TCGRF / VerticalMergeFlag assign formatting and content to the origin.
    Unrelated cells may change grids, and horizontal groups may represent the
    same interval using different physical cells. Like the output builder,
    ignore vertical flags on horizontally covered cells. Require empty source
    continuations because the extractor retains unexpected covered text.
    """
    if not any(flag & 0x60 for _, props, _ in rows for flag in props.flags):
        return False
    previous = set()
    for _, props, cells in rows:
        if (len(props.flags) != len(cells) or len(props.edges) != len(cells) + 1
                or any(a >= b for a, b in zip(props.edges, props.edges[1:]))
                or not cell_ownership(props, cells, vertical=True)):
            return False
        current = set()
        c = 0
        while c < len(cells):
            flag = props.flags[c]
            stop = c + 1
            if flag & 3 in (2, 3):
                while stop < len(cells) and props.flags[stop] & 3 == 1:
                    stop += 1
            budget.record(stop - c)
            key = props.edges[c], props.edges[stop]
            vertical = flag & 0x60
            if vertical == 0x40:
                return False
            if vertical == 0x60:
                current.add(key)
            elif vertical == 0x20:
                cell = cells[c]
                if key not in previous or not empty_cell(cell):
                    return False
                current.add(key)
            c = stop
        previous = current
    return True


def apply_conditions(doc, paragraphs):
    # Nothing to prove for unconditional-only documents.
    if not any(local for local, _, _ in doc.styles.conditions.values()):
        return
    bookmark_unknown = any(len(doc.pairs) >= (i + 1) * 8 and doc.pair(i)[1]
                           for i in (137, 138, 139, 141, 142, 143))
    levels = []
    visibility_cache = {}

    def finish(level):
        rows = level['rows']
        if not rows:
            return
        wanted = any(doc.styles.table_conditions(p.applied_table_style)[0] for _, p, _ in rows)
        if not wanted:
            return
        safe = not (level['unsafe'] or level['nested'] or level['pending'] or bookmark_unknown)
        vertical = vertical_row_context(rows, doc.budget)
        for entries, p, cells in rows:
            conditions, bands, unsafe = doc.styles.table_conditions(p.applied_table_style)
            safe &= (not unsafe and p.condition_known and bool(cells)
                     and len(p.edges) == len(cells) + 1
                     and all(a <= b for a, b in zip(p.edges, p.edges[1:]))
                     and len(p.flags) == len(cells))
            safe &= cell_ownership(p, cells, vertical)
        # A style on an adjacent row can alter the boundary even if it has no CCnf.
        if not safe:
            doc.warn(diagnostic_warning('doc_conditional_table_visibility_has_no_proven_stable_rectangular_context', 'Conditional table visibility has no proven stable rectangular context; unconditional visibility is retained.'))
            for entries, _, _ in rows:
                for item in entries:
                    item[6] = False
            return
        prefix = True
        headers = []
        for _, p, _ in rows:
            prefix = prefix and p.table_header
            headers.append(prefix)
        excluded = 0
        for r, (entries, p, cells) in enumerate(rows):
            conditions, bands, _ = doc.styles.table_conditions(p.applied_table_style)
            # Counting exclusions use this row's effective table options.
            ordinal = r
            if p.table_look & 0x20:
                ordinal -= excluded
            excluded += r == 0 or headers[r]
            for c, cell in enumerate(cells):
                # TDefTable defines columns per row (2.6.3), not on the
                # normalized output grid. TCGRF extends the origin's formatting
                # over its horizontal continuations; their empty source marks
                # do not move the origin to the last column of its span.
                matches = tuple(matched(p.table_look, r, c, len(rows), len(cells),
                                        headers[r], ordinal, bands))
                key = p.applied_table_style, matches, cell[0][5]
                if key not in visibility_cache:
                    doc.budget.record()
                    visibility_cache[key] = doc.styles.conditional_hidden(
                        p.applied_table_style, matches)
                value = visibility_cache[key]
                for item in cell:
                    item[5] = value

    def close():
        level = levels.pop()
        finish(level)

    for item in paragraphs:
        props, mark = item[4], item[2]
        depth = props.depth or (1 if props.in_table else 0)
        while len(levels) > depth:
            close()
        while len(levels) < depth:
            doc.budget.record()
            if levels:
                # Record where the child occurs among direct parent paragraphs.
                # Do not copy its entries: its innermost style owns them. This
                # also marks implicit ancestors when the source skips depths.
                levels[-1]['nested'].add(len(levels[-1]['pending']))
            levels.append({'rows': [], 'pending': [], 'unsafe': False, 'nested': set()})
        if not depth:
            continue
        level = levels[-1]
        doc.budget.record()
        level['pending'].append(item)
        if not (props.row_end if depth == 1 else props.inner_ttp):
            continue
        entries = level['pending']
        level['pending'] = []
        nested = level['nested']
        level['nested'] = set()
        cells, pending = [], _CellEntries()
        for index, entry in enumerate(entries[:-1]):
            pending.nested |= index in nested
            pending.append(entry)
            if (entry[2] == 7 if depth == 1 else entry[4].inner_cell):
                cells.append(pending)
                pending = _CellEntries()
        # A nested table immediately before TTP lacks a parent cell mark.
        row_unsafe = len(entries) - 1 in nested
        frame = entries[0][4].frame if cells else None
        rows = level['rows']
        if rows:
            previous, prev_props, _ = rows[-1]
            if row_boundary(prev_props.identity, prev_props.bidi or prev_props.bidi90,
                            previous[0][4].frame, props, frame):
                # Do not allow unknown style frame contributions on either side
                # to make an otherwise uncertain boundary look proven.
                risky = (doc.styles.table_conditions(prev_props.applied_table_style)[2]
                         or doc.styles.table_conditions(props.applied_table_style)[2]
                         or not prev_props.condition_known or not props.condition_known)
                level['unsafe'] |= risky
                finish(level)
                level['rows'] = []
                level['unsafe'] = risky
        level['unsafe'] |= (row_unsafe or bool(pending) or item[0] != item[1] or mark == 0
                            or (depth == 1 and mark != 7)
                            or (depth > 1 and any(e[2] == 7 or e[4].row_end for e in entries)))
        doc.budget.record()
        level['rows'].append((entries, props, cells))
    while levels:
        close()
