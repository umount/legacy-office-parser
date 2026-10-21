"""Bounded numeric display subset, not an Excel format interpreter.

Return None for unsupported syntax; never strip literals into executable tokens.
See docs/research-xls-formats.md for grammar, rounding, bounds and provenance.
"""
from __future__ import annotations

import re
import operator
from decimal import Context, Decimal, ROUND_HALF_UP, localcontext


BUILTIN_NUMERIC = {
    0: 'General', 1: '0', 2: '0.00', 3: '#,##0', 4: '#,##0.00',
    9: '0%', 10: '0.00%', 11: '0.00E+00',
}
MAX_FORMAT_LENGTH = 64
_COLOR = re.compile(r'\[(?:Black|Blue|Cyan|Green|Magenta|Red|White|Yellow)\]', re.I)
# MS-XLS 2.4.126 NFPartCondNum, restricted to an ASCII, finite binary64
# threshold and at most three exponent digits. Never use eval or ambient Decimal
# arithmetic to interpret conditions.
_CONDITION = re.compile(r'\[(<=|>=|<>|<|>|=)(-?[0-9]+(?:\.[0-9]+)?(?:E[+-][0-9]{1,3})?)\]')
_COMPARE = {'<': operator.lt, '<=': operator.le, '>': operator.gt,
            '>=': operator.ge, '=': operator.eq, '<>': operator.ne}
_MAX_THRESHOLD = Decimal('1.7976931348623157E+308')
_MIN_THRESHOLD = Decimal('5E-324')
_FIXED = re.compile(r'(0|#,##0)(?:\.(0{1,15}))?(%)?')
_SCIENTIFIC = re.compile(r'0(?:\.(0{1,15}))?([Ee])([+-])(0{1,3})')
_DATE_TOKEN = re.compile(
    r'am/pm|a/p|y+|m+|d+|h+|s+|[ /:.,-]+|\\[ /:.,-]|"[ /:.,-]+"', re.I,
)


def simple_date_format(code: str) -> bool:
    """Gate the legacy date recognizer: allow only date tokens and plain/quoted/escaped separators."""
    if len(code) > MAX_FORMAT_LENGTH:
        return False
    end, has_date = 0, False
    for match in _DATE_TOKEN.finditer(code.lower()):
        if match.start() != end:
            return False
        token = match.group()
        if token[0] in 'ymdhs':
            sizes = {'y': (2, 4), 'm': (1, 2, 3, 4, 5), 'd': (1, 2, 3, 4),
                     'h': (1, 2), 's': (1, 2)}
            if len(token) not in sizes[token[0]]:
                return False
            has_date = True
        end = match.end()
    return end == len(code) and has_date


def _numeric_parts(code: str, *, allow_literal: bool = False) -> tuple[str, str, str] | None:
    """Split explicit affixes from one contiguous core; never join split masks.

    Quotes (including empty pairs) enclose verbatim text; outside quotes a
    backslash consumes exactly one literal character. Bare signs/parentheses
    are affixes; scientific exponent signs are consumed with the numeric core.
    """
    prefix, suffix = [], []
    core = None
    bare_affix = False
    pos = 0
    while pos < len(code):
        char = code[pos]
        if char == '"':
            end = code.find('"', pos + 1)
            if end < 0:
                return None
            literal = code[pos + 1:end]
            pos = end + 1
        elif char == '\\':
            if pos + 1 == len(code):
                return None
            literal = code[pos + 1]
            pos += 2
        elif char in '+-()':
            literal = char
            bare_affix = True
            pos += 1
        else:
            if core is not None:
                return None
            match = _SCIENTIFIC.match(code, pos) or _FIXED.match(code, pos)
            if match is None:
                return None
            core = match.group()
            pos = match.end()
            continue
        (prefix if core is None else suffix).append(literal)
    if core is None:
        if not allow_literal or bare_affix or not ''.join(prefix):
            return None
        core = ''
    return ''.join(prefix), core, ''.join(suffix)


def _split_sections(code: str) -> list[str] | None:
    """Bounded split with the same quote/escape rules as numeric affixes."""
    if not code or len(code) > MAX_FORMAT_LENGTH:
        return None
    sections = []
    start = pos = 0
    while pos < len(code):
        char = code[pos]
        if char == '"':
            end = code.find('"', pos + 1)
            if end < 0:
                return None
            pos = end + 1
        elif char == '\\':
            if pos + 1 == len(code):
                return None
            pos += 2
        elif char == ';':
            sections.append(code[start:pos])
            if not sections[-1] or len(sections) == 4:
                return None
            pos += 1
            start = pos
        else:
            pos += 1
    sections.append(code[start:])
    return sections if sections[-1] else None


def _with_affixes(text: str, prefix: str, suffix: str) -> str:
    # The implicit single-section minus precedes the whole display, including
    # its literal prefix. Use the rendered sign so rounded zero stays unsigned.
    if text.startswith('-'):
        return '-' + prefix + text[1:] + suffix
    return prefix + text + suffix


def render_number(value: int | float, code: str) -> str | None:
    """Render a finite BIFF number without altering its stored Python value.

    Decimal uses the shortest round-trip string, with explicit half-up rounding.
    A private context avoids ambient decimal precision/traps/rounding settings.
    Precision 340 covers finite binary64 fixed output plus percent and 15 places.
    """
    sections = _split_sections(code)
    if sections is None:
        return None
    if len(sections) == 4:
        if sections.pop() != '@':
            return None
    parsed = []
    conditions = []
    for index, section in enumerate(sections):
        color = _COLOR.match(section)
        if color:
            section = section[color.end():]
        condition = _CONDITION.match(section)
        if condition:
            if index > 1:
                return None
            op, threshold_text = condition.groups()
            threshold = Decimal(threshold_text)
            magnitude = threshold.copy_abs()
            if magnitude > _MAX_THRESHOLD or (magnitude and magnitude < _MIN_THRESHOLD):
                return None
            # Do not choose between decimal-exact and binary64-rounded branch
            # selection for an overprecise threshold. Accept only values equal
            # to their binary64 shortest-round-trip decimal representation.
            # Decimal(string), float conversion and finite Decimal comparison
            # do not round through or mutate the caller's Decimal context.
            if threshold != Decimal(str(float(threshold))):
                return None
            conditions.append((op, threshold))
            section = section[condition.end():]
            # Excel's custom-format guidance and Calc XLS export also place the
            # one color token after the condition. Do not accept duplicates.
            if color is None:
                color = _COLOR.match(section)
                if color:
                    section = section[color.end():]
        else:
            conditions.append(None)
        if section.lower() == 'general':
            parts = ('', 'General', '')
        else:
            parts = _numeric_parts(section, allow_literal=index == 2)
        if parts is None:
            return None
        parsed.append(parts)

    # Validate the complete format before routing, including unused sections.
    # Deliberately exclude mixed implicit/explicit three-section routing and a
    # condition in section two alone: importers disagree on these combinations.
    conditional = any(condition is not None for condition in conditions)
    if conditional:
        if conditions[0] is None or (len(parsed) == 3 and conditions[1] is None):
            return None
        # The MS-XLS single-section conditional production is General only.
        if len(parsed) == 1 and parsed[0][1] != 'General':
            return None
        number = Decimal(str(value))
        if not number.is_finite():
            return None
        # INCOMPLETE: MS-XLS 2.4.126 specifies condition syntax and delegates
        # display semantics to ECMA-376 18.8.31. The consulted primary text does
        # not establish conditional negative-sign handling. Calc observations
        # are not a normative rule for arbitrary Excel formats. Reject EVERY
        # negative conditional value, including General and literal fallbacks,
        # rather than extrapolating a sign whitelist from finite probes.
        # Signed zero still follows numeric zero routing; its raw bits survive.
        if number < 0:
            return None
        selected = None
        for index, condition in enumerate(conditions):
            if condition is None or _COMPARE[condition[0]](number, condition[1]):
                selected = index
                break
        if selected is None:
            # Excel's unmatched display is width-dependent hashes. Keep the raw
            # value and warn instead of inventing text or an implicit General.
            return None
        if (not number and len(parsed) == 2 and conditions[1] is None
                and conditions[0] == ('>', Decimal(0))):
            # Calc normalizes this to ordinary sign sections (zero goes first),
            # contrary to literal predicate selection. Do not guess at zero.
            return None
    else:
        # Route on the stored value, before rounding. Both signed zeros use zero.
        selected = 1 if value < 0 and len(parsed) > 1 else (
            2 if value == 0 and len(parsed) == 3 else 0
        )
        if selected == 1:
            value = abs(value)
    prefix, core, suffix = parsed[selected]
    if core == 'General':
        return str(value)
    fixed = _FIXED.fullmatch(core)
    scientific = _SCIENTIFIC.fullmatch(core)
    with localcontext(Context(prec=340, rounding=ROUND_HALF_UP)):
        number = Decimal(str(value))
        if not number.is_finite():
            return None
        if not core:  # Explicit, nonempty literal-only third section.
            return prefix
        if fixed is not None:
            integer, fraction, percent = fixed.groups()
            places = len(fraction or '')
            if percent:
                number *= 100
            number = number.quantize(Decimal(1).scaleb(-places))
            if not number:
                number = number.copy_abs()
            grouping = ',' if integer == '#,##0' else ''
            text = format(number, f'{grouping}.{places}f') + ('%' if percent else '')
            return _with_affixes(text, prefix, suffix)
        fraction, letter, sign, zeros = scientific.groups()
        places = len(fraction or '')
        mantissa, exponent = format(number, f'.{places}E').split('E')
        power = int(exponent) if number else 0
        if not number:
            mantissa = format(Decimal(0), f'.{places}f')
        exponent_sign = '-' if power < 0 else ('+' if sign == '+' else '')
        text = mantissa + letter + exponent_sign + str(abs(power)).zfill(len(zeros))
        return _with_affixes(text, prefix, suffix)
