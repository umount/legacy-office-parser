"""Conservative XLSX oracle for LibreOffice corpus comparisons (stdlib only).

compare_spreadsheets(Document, open ZipFile) returns JSON-safe diagnostics, never
names, values, formula expressions, format codes, paths, or exception messages.
Sheet numbers are 1-based workbook positions. `equal` concerns stored semantics
only: display text, number rendering, formula expressions and cache freshness
are NOT checked. LibreOffice may recalculate caches. Blank non-formula cells
are ignored on both sides; merges are checked independently. Numeric ODS
float/percentage/currency types normalize to number (formatting is out of scope).
Unknown formats never imply equality. No parser implementation is reused.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from decimal import Decimal, InvalidOperation
import math
import posixpath
import re
import xml.etree.ElementTree as ET
from zipfile import BadZipFile

_NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
_R = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
_N = '{' + _NS + '}'


@dataclass
class _Cell:
    kind: str
    value: object
    formula: bool = False
    problem: str | None = None
    boolean_constant: bool | None = None


class _Unsupported(Exception):
    pass


def _xml(archive, path):
    return ET.fromstring(archive.read(path))


def _rels(archive, part):
    path = posixpath.join(posixpath.dirname(part), '_rels',
                          posixpath.basename(part) + '.rels') if part else '_rels/.rels'
    result = {}
    for rel in _xml(archive, path):
        key = rel.attrib['Id']
        if key in result:
            raise ValueError
        target = rel.attrib['Target']
        resolved = posixpath.normpath(posixpath.join(posixpath.dirname(part), target)).lstrip('/')
        if resolved.startswith('../'):
            raise ValueError
        result[key] = (rel.attrib['Type'].rsplit('/', 1)[-1], resolved,
                       rel.get('TargetMode') == 'External')
    return result


def _coord(address):
    match = re.fullmatch(r'([A-Z]{1,3})([1-9][0-9]{0,6})', address)
    if not match:
        raise ValueError
    col = 0
    for char in match[1]:
        col = col * 26 + ord(char) - 64
    row = int(match[2])
    if col > 16384 or row > 1048576:
        raise ValueError
    return row, col


def _range(address):
    parts = address.split(':')
    if len(parts) not in (1, 2):
        raise ValueError
    start, end = _coord(parts[0]), _coord(parts[-1])
    if start[0] > end[0] or start[1] > end[1]:
        raise ValueError
    return (*start, *end)


def _string(element):
    # Phonetic annotation rPh is not part of the stored string.
    value = ''.join(child.text or '' for child in element.findall(_N + 't'))
    if element.find(_N + 't') is None:
        value = ''.join(t.text or '' for run in element.findall(_N + 'r')
                        for t in run.findall(_N + 't'))
    # OOXML escaping is decoded in one pass: _x005F_x0041_ is literal _x0041_.
    value = re.sub(r'_x([0-9a-fA-F]{4})_', lambda m: chr(int(m[1], 16)), value)
    return value.encode('utf-16-le', 'surrogatepass').decode('utf-16-le')


def _format(fmt, custom):
    if fmt in custom:
        code = custom[fmt].lower().strip()
        # LO exports calendar separators escaped (sometimes double escaped).
        code = re.sub(r'\\+(?=[/ :.-])', '', code)
        if code in {'general', '0', '0.00', '#,##0', '#,##0.00', '0%', '0.00%',
                    '0.00e+00', '@'}:
            return 'number'
        if code in {'yyyy-mm-dd', 'yyyy/mm/dd', 'mm/dd/yyyy', 'm/d/yy',
                    'dd/mm/yyyy', 'd-mmm-yy', 'yyyy-mm-dd hh:mm:ss',
                    'yyyy-mm-dd"t"hh:mm:ss'}:
            return 'date'
        if code in {'hh:mm', 'hh:mm:ss', 'h:mm', 'h:mm:ss', 'mm:ss'}:
            return 'clock'
        return 'unsupported'
    if fmt in {14, 15, 16, 17, 22}:
        return 'date'
    if fmt in {18, 19, 20, 21, 45, 47}:
        return 'clock'
    if fmt in set(range(14)) | set(range(37, 45)) | {48, 49}:
        return 'number'
    return 'unsupported'  # elapsed time, locale-dependent and missing custom IDs


def _date(value, epoch1904, clock):
    if value < 0 or (not epoch1904 and not clock and 60 <= value < 61):
        return None
    # Reject precision the model cannot represent, even below datetime's microsecond.
    milliseconds = value * Decimal(86400000)
    if milliseconds != milliseconds.to_integral_value():
        return None
    serial = value if epoch1904 or value < 60 else value - 1
    try:
        base = datetime(1904, 1, 1) if epoch1904 else datetime(1899, 12, 31)
        dt = base + timedelta(days=float(serial))
        # The model's XLS dates have millisecond precision. Do not round away
        # submillisecond reference information and claim exact agreement.
        if dt.microsecond % 1000:
            return None
        return dt.time() if clock else dt
    except (OverflowError, ValueError):
        return None


def _cell(element, strings, styles, custom, epoch1904):
    typ = element.get('t', 'n')
    formula = element.find(_N + 'f') is not None
    v = element.find(_N + 'v')
    raw = None if v is None else v.text
    if formula and (v is None or (raw is None and typ != 'str')):
        return _Cell('empty', None, True, 'missing_formula_cache')
    if typ == 'inlineStr':
        inline = element.find(_N + 'is')
        if inline is None:
            raise ValueError
        return _Cell('string', _string(inline), formula)
    if typ == 'str':
        return _Cell('string', raw or '', formula)
    if typ not in {'n', 's', 'b', 'e', 'd'}:
        return _Cell('unknown', None, formula, 'unsupported_cell_type')
    if raw is None:
        if typ != 'n':
            raise ValueError
        return _Cell('empty', None, formula)
    if typ == 's':
        index = int(raw)
        if index < 0:
            raise ValueError
        return _Cell('string', strings[index], formula)
    if typ == 'b':
        if raw not in {'0', '1', 'false', 'true'}:
            raise ValueError
        cached = raw in {'1', 'true'}
        expression = element.find(_N + 'f')
        literal = (expression.text or '').strip().upper() if expression is not None else ''
        constant = {'TRUE()': True, 'FALSE()': False}.get(literal)
        return _Cell('boolean', cached, formula, boolean_constant=constant)
    if typ == 'e':
        return _Cell('error', raw, formula)
    if typ == 'd':
        parsed = datetime.fromisoformat(raw)
        return _Cell('date', parsed, formula,
                     'timezone_date' if parsed.tzinfo else None)
    number = Decimal(raw)
    if not number.is_finite():
        raise ValueError
    style = int(element.get('s', '0'))
    if style < 0 or style >= len(styles):
        return _Cell('number', number, formula, 'unsupported_style')
    category = _format(styles[style], custom)
    if category == 'unsupported':
        return _Cell('number', number, formula, 'unsupported_number_format')
    if category == 'number':
        return _Cell('number', number, formula)
    date = _date(number, epoch1904, category == 'clock')
    return _Cell('date', date, formula, 'ambiguous_date' if date is None else None)


def _style_format(xf, bases):
    """Resolve stored number format, not the appearance of a named style.

    MS-OE376 3.8.45: applyNumberFormat controls propagation of parent changes.
    LO omits it even when the stored cell format differs from the parent.
    An explicit false with conflicting IDs is conservatively unresolved.
    """
    flag = xf.get('applyNumberFormat')
    if flag not in {None, '0', '1', 'false', 'true'}:
        raise ValueError
    parent = None
    if 'xfId' in xf.attrib:
        index = int(xf.attrib['xfId'])
        if index < 0 or index >= len(bases):
            return -1
        parent = int(bases[index].get('numFmtId', '0'))
    direct = xf.get('numFmtId')
    if direct is None:
        return parent if parent is not None else 0
    direct = int(direct)
    if flag in {'0', 'false'} and (parent is None or direct != parent):
        return -1
    return direct


def _numeric_equal(value, reference):
    """Compare in the model's numeric domain, without an arbitrary epsilon.

    XLS NUMBER/RK and ODS floats are binary64; different decimal spellings that
    round to the SAME finite binary64 are equivalent. Integers retain exact
    precision for equality. LO can also round exports to 15 significant digits: those cases
    are inconclusive, never silently equal, if binary64 values differ.
    """
    exact = Decimal(str(value))
    if exact == reference:
        return True
    if isinstance(value, int):
        # A 15-significant-digit LO export can also round an exact ODS integer.
        # Do not classify arbitrary nearby integers as conversion rounding.
        return None if reference == Decimal(format(exact, '.15g')) else False
    if isinstance(value, float):
        converted = float(reference)
        if math.isfinite(converted) and converted == value:
            return True
        if math.isfinite(converted) and format(value, '.15g') == format(converted, '.15g'):
            return None
    return False


def _read(archive):
    roots = [r for r in _rels(archive, '').values() if r[0] == 'officeDocument']
    if len(roots) != 1 or roots[0][2]:
        raise ValueError
    part = roots[0][1]
    workbook = _xml(archive, part)
    if workbook.tag != _N + 'workbook':
        raise _Unsupported
    rels = _rels(archive, part)
    props = workbook.find(_N + 'workbookPr')
    epoch = props.get('date1904', '0') if props is not None else '0'
    if epoch not in {'0', '1', 'true', 'false'}:
        raise ValueError
    strings, custom, styles = [], {}, [0]
    for kind in ('sharedStrings', 'styles'):
        matching = [r for r in rels.values() if r[0] == kind]
        if len(matching) > 1 or any(r[2] for r in matching):
            raise ValueError
        if not matching:
            continue
        root = _xml(archive, matching[0][1])
        if kind == 'sharedStrings':
            strings = [_string(si) for si in root.findall(_N + 'si')]
        else:
            custom = {int(f.attrib['numFmtId']): f.attrib['formatCode']
                      for f in root.findall(_N + 'numFmts/' + _N + 'numFmt')}
            bases = root.findall(_N + 'cellStyleXfs/' + _N + 'xf')
            styles = [_style_format(xf, bases) for xf in
                      root.findall(_N + 'cellXfs/' + _N + 'xf')]
    sheets = []
    for entry in workbook.findall(_N + 'sheets/' + _N + 'sheet'):
        kind, path, external = rels[entry.attrib[_R + 'id']]
        if external or kind != 'worksheet':
            raise _Unsupported
        root = _xml(archive, path)
        if root.tag != _N + 'worksheet':
            raise _Unsupported
        state = entry.get('state', 'visible')
        if state not in {'visible', 'hidden', 'veryHidden'}:
            raise ValueError
        cells = {}
        for element in root.findall(_N + 'sheetData/' + _N + 'row/' + _N + 'c'):
            coord = _coord(element.attrib['r'])
            if coord in cells:
                raise ValueError
            cells[coord] = _cell(element, strings, styles, custom, epoch in {'1', 'true'})
        merges = Counter(_range(m.attrib['ref']) for m in
                         root.findall(_N + 'mergeCells/' + _N + 'mergeCell'))
        sheets.append((entry.attrib['name'], state != 'visible', cells, merges))
    return sheets


def _nonblank(cell):
    return cell.formula or cell.kind != 'empty' or cell.value is not None


def _model_value(cell, ref):
    kind = {'float': 'number', 'percentage': 'number', 'currency': 'number'}.get(
        cell.value_type, cell.value_type)
    value = cell.value
    if kind == 'number':
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError
        value = Decimal(str(value))
        if not value.is_finite():
            raise ValueError
    if kind == 'boolean' and type(value) is not bool:
        raise ValueError
    if kind in {'string', 'error'} and not isinstance(value, str):
        raise ValueError
    if kind == 'date':
        value = (time.fromisoformat(value) if isinstance(ref.value, time)
                 else datetime.fromisoformat(value))
        if value.tzinfo:
            raise _Unsupported
    return kind, value


def compare_spreadsheets(doc, zipfile) -> dict:
    """Compare against an open XLSX ZipFile; report only counts and coordinates.

    status: equal / different / ambiguous / unsupported / invalid_reference.
    `equal` is None for inconclusive checks, False for proven differences.
    Differences take precedence, but all uncertainty remains in issues/counts.
    Numeric comparison uses the model domain (exact int / finite binary64);
    differing binary64 values consistent with LO rounding remain ambiguous.
    Exceptions from malformed reference data are sanitized at this boundary.
    """
    result = {'status': 'equal', 'equal': True, 'sheets': len(doc.sheets),
              'reference_sheets': 0, 'cells': 0, 'reference_cells': 0,
              'compared_cells': 0, 'issues': [], 'counts': {}}

    def issue(reason, sheet=None, coordinate=None):
        item = {'reason': reason}
        if sheet is not None:
            item['sheet'] = sheet
        if coordinate is not None:
            item['coordinate'] = list(coordinate)
        result['issues'].append(item)

    try:
        refs = _read(zipfile)
    except _Unsupported:
        result.update(status='unsupported', equal=None)
        issue('unsupported_reference')
        result['counts'] = {'unsupported_reference': 1}
        return result
    except (KeyError, ValueError, IndexError, TypeError, InvalidOperation,
            ET.ParseError, BadZipFile, OSError, OverflowError):
        result.update(status='invalid_reference', equal=None)
        issue('invalid_reference')
        result['counts'] = {'invalid_reference': 1}
        return result
    result['reference_sheets'] = len(refs)
    result['reference_cells'] = sum(sum(_nonblank(c) for c in s[2].values()) for s in refs)
    result['cells'] = sum(sum(c.is_formula or c.value_type != 'empty' or c.value is not None
                              for c in s.cells) for s in doc.sheets)
    for i in range(max(len(doc.sheets), len(refs))):
        if i >= len(doc.sheets) or i >= len(refs):
            issue('missing_sheet' if i >= len(doc.sheets) else 'extra_sheet', i + 1)
            continue
        sheet = doc.sheets[i]
        name, hidden, cells, merges = refs[i]
        if sheet.name != name:
            issue('sheet_name_or_order', i + 1)
        if sheet.hidden != hidden:
            issue('hidden', i + 1)
        got = {}
        for c in sheet.cells:
            key = c.row, c.column
            if key in got:
                issue('duplicate_coordinate', i + 1, key)
            got[key] = c
        got = {k: c for k, c in got.items() if c.is_formula or c.value_type != 'empty'
               or c.value is not None}
        cells = {k: c for k, c in cells.items() if _nonblank(c)}
        for key in sorted(got.keys() | cells.keys()):
            if key not in got or key not in cells:
                issue('missing_cell' if key not in got else 'extra_cell', i + 1, key)
                continue
            c, ref = got[key], cells[key]
            if c.is_formula != ref.formula:
                # LO may replace XLS BOOLERR literals with constant formulas.
                # Document alone cannot prove provenance: keep this inconclusive.
                converted_boolean = (not c.is_formula and ref.formula
                                     and type(c.value) is bool and c.value_type == 'boolean'
                                     and ref.boolean_constant is c.value
                                     and ref.value is c.value)
                issue('conversion_boolean_formula' if converted_boolean else 'formula_flag',
                      i + 1, key)
            if ref.problem:
                issue(ref.problem, i + 1, key)
                continue
            if c.is_formula and c.value is None:
                issue('missing_formula_cache', i + 1, key)
                continue
            if c.value_type == 'time':
                issue('unsupported_duration', i + 1, key)
                continue
            try:
                kind, value = _model_value(c, ref)
            except _Unsupported:
                issue('timezone_date', i + 1, key)
                continue
            except (ValueError, TypeError, InvalidOperation):
                issue('invalid_model_value', i + 1, key)
                continue
            result['compared_cells'] += 1
            if kind != ref.kind:
                issue('type', i + 1, key)
            elif kind == 'number':
                same = _numeric_equal(c.value, ref.value)
                if same is not True:
                    issue('ambiguous_numeric_precision' if same is None else 'value', i + 1, key)
            elif value != ref.value:
                issue('value', i + 1, key)
        actual = Counter((m.start_row, m.start_column, m.end_row, m.end_column)
                         for m in sheet.merges)
        for reason, ranges in [('missing_merge', merges - actual),
                               ('extra_merge', actual - merges)]:
            for coords, count in sorted(ranges.items()):
                for _ in range(count):
                    issue(reason, i + 1, coords)
    counts = Counter(item['reason'] for item in result['issues'])
    result['counts'] = dict(sorted(counts.items()))
    ambiguous = {'missing_formula_cache', 'ambiguous_date', 'timezone_date',
                 'conversion_boolean_formula', 'ambiguous_numeric_precision'}
    uncertain = ambiguous | {r for r in counts if r.startswith('unsupported_')}
    if counts.keys() - uncertain:
        result.update(status='different', equal=False)
    elif counts:
        result.update(status='ambiguous' if counts.keys() & ambiguous else 'unsupported', equal=None)
    return result
