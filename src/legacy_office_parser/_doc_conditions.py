"""Narrow, bounded conditional visibility on proven structural table partitions."""
from ._doc_styles import toggle


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
        safe = not (level['unsafe'] or level['row_unsafe'] or level['pending'] or bookmark_unknown)
        grid = rows[0][1].edges
        for entries, p, cells in rows:
            conditions, bands, unsafe = doc.styles.table_conditions(p.applied_table_style)
            safe &= (not unsafe and p.condition_known and bool(cells)
                     and len(grid) == len(cells) + 1 and p.edges == grid
                     and all(a < b for a, b in zip(grid, grid[1:]))
                     and not any(f & 0x63 for f in p.flags)
                     and len(p.flags) == len(cells))
        # A style on an adjacent row can alter the boundary even if it has no CCnf.
        if not safe:
            doc.warn('Conditional table visibility has no proven stable rectangular context; unconditional visibility is retained.')
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
                matches = tuple(matched(p.table_look, r, c, len(rows), len(cells), headers[r], ordinal, bands))
                key = p.applied_table_style, matches, cell[0][5]
                if key not in visibility_cache:
                    doc.budget.record()
                    value = cell[0][5]
                    for condition in matches:
                        for operations in conditions.get(condition, ()):
                            parent = value
                            for operand in operations:
                                doc.budget.record()
                                value = toggle(operand, parent)
                    visibility_cache[key] = value
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
                # Nesting belongs to the pending row, whose table boundary
                # is not known until its TTP. Do not taint earlier partitions.
                levels[-1]['row_unsafe'] = True
            levels.append({'rows': [], 'pending': [], 'unsafe': False, 'row_unsafe': False})
        if not depth:
            continue
        level = levels[-1]
        doc.budget.record()
        level['pending'].append(item)
        if not (props.row_end if depth == 1 else props.inner_ttp):
            continue
        entries = level['pending']
        level['pending'] = []
        row_unsafe = level['row_unsafe']
        level['row_unsafe'] = False
        cells, pending = [], []
        for entry in entries[:-1]:
            pending.append(entry)
            if (entry[2] == 7 if depth == 1 else entry[4].inner_cell):
                cells.append(pending)
                pending = []
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
                            or (depth > 1 and any(e[2] == 7 or e[4].row_end for e in entries)))
        doc.budget.record()
        level['rows'].append((entries, props, cells))
    while levels:
        close()
