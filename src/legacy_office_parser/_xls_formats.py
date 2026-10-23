"""Bounded numeric display subset, not an Excel format interpreter.

Return None for unsupported syntax; never strip literals into executable tokens.
Canonical ASCII numeric cores are localized only before attaching literals.
See test_xls_numeric_completeness.py for primary sources and policy differences.
"""
from __future__ import annotations

import re
import operator
from decimal import Context, Decimal, ROUND_HALF_UP, localcontext
from fractions import Fraction

from .number_locale import NumberLocale


BUILTIN_NUMERIC = {
    0: 'General', 1: '0', 2: '0.00', 3: '#,##0', 4: '#,##0.00',
    9: '0%', 10: '0.00%', 11: '0.00E+00',
    12: '# ?/?', 13: '# ??/??',
    37: '#,##0 ;(#,##0)', 38: '#,##0 ;[Red](#,##0)',
    39: '#,##0.00;(#,##0.00)', 40: '#,##0.00;[Red](#,##0.00)',
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
_FIXED = re.compile(r'([#0?]+(?:,[#0?]+)*)(?:\.([#0?]{0,15}))?(,{0,63})(%)?')
# Currency names are authored literals; LCIDs never select separators here.
_CURRENCY = re.compile(r'\[\$([^\[\]]+)-([0-9A-Fa-f]{3,8})\]')
_PLAIN_LOCALE = re.compile(r'\[\$-([0-9A-Fa-f]{3,8})\]')
_ORDINARY_LOCALES = {0x409, 0x809, 0x407, 0x419, 0x40c}
# Fixed denominators remain unreduced. Variable denominators have at most
# three digits: bounded continued-fraction approximation, not a value whitelist.
_FRACTION = re.compile(r'(0 )?(0{1,3})/([1-9][0-9]{0,2})')
_VARIABLE_FRACTION = re.compile(r'# (\?{1,3})/(\?{1,3})')
_BARE_LITERAL = " +-()$€£¥:!^&'~{}<=>"
_SCIENTIFIC = re.compile(r'0(?:\.(0{1,15}))?([Ee])([+-])(0{1,3})')
def _numeric_parts(code: str, *, allow_literal: bool = False) -> tuple[str, str, str] | None:
    """Split explicit affixes from one contiguous core; never join split masks.

    Quotes (including empty pairs) enclose verbatim text; outside quotes a
    backslash consumes exactly one literal character. Bare signs/parentheses
    are affixes; scientific exponent signs are consumed with the numeric core.
    """
    prefix, suffix = [], []
    core = None
    bare_affix = False
    currency = False
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
        elif char == '[':
            token = _CURRENCY.match(code, pos)
            plain = _PLAIN_LOCALE.match(code, pos)
            if currency:
                return None
            if token is not None:
                literal = token[1]
                if any(ord(c) < 32 for c in literal):
                    return None
            elif plain is not None and int(plain[1], 16) in _ORDINARY_LOCALES:
                token, literal = plain, ''
            else:
                return None
            currency = True
            pos = token.end()
        elif char in '_*':
            if pos + 1 == len(code):
                return None
            # Width-free text projection: one alignment space, no fill repeats.
            literal = ' ' if char == '_' else ''
            pos += 2
        elif char in _BARE_LITERAL:
            literal = char
            bare_affix = True
            pos += 1
        else:
            if core is not None:
                return None
            match = (_VARIABLE_FRACTION.match(code, pos) or _FRACTION.match(code, pos)
                     or _SCIENTIFIC.match(code, pos)
                     or _FIXED.match(code, pos))
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
        elif char in '\\_*':
            if pos + 1 == len(code):
                return None
            pos += 2
        elif char == ';':
            sections.append(code[start:pos])
            if len(sections) == 4:
                return None
            pos += 1
            start = pos
        else:
            pos += 1
    sections.append(code[start:])
    return sections


def _text_parts(section: str, *, literal_only: bool = False) -> tuple[str, str] | None:
    """Quoted/escaped literals with one @, or no @ in literal-only mode."""
    color = _COLOR.match(section)
    if color:
        section = section[color.end():]
    prefix, suffix = [], []
    placeholder = False
    pos = 0
    while pos < len(section):
        char = section[pos]
        if char == '@':
            if placeholder or literal_only:
                return None
            placeholder = True
            pos += 1
            continue
        if char == '"':
            end = section.find('"', pos + 1)
            if end < 0:
                return None
            literal = section[pos + 1:end]
            pos = end + 1
        elif char == chr(92) and pos + 1 < len(section):
            literal = section[pos + 1]
            pos += 2
        elif char in '_*' and pos + 1 < len(section):
            literal = ' ' if char == '_' else ''
            pos += 2
        elif char in _BARE_LITERAL:
            literal = char
            pos += 1
        else:
            return None
        (suffix if placeholder else prefix).append(literal)
    return (''.join(prefix), ''.join(suffix)) if placeholder or literal_only else None


def _with_affixes(text: str, prefix: str, suffix: str) -> str:
    # The implicit single-section minus precedes the whole display, including
    # its literal prefix. Use the rendered sign so rounded zero stays unsigned.
    if text.startswith('-'):
        return '-' + prefix + text[1:] + suffix
    return prefix + text + suffix


def _render_fraction(number: Decimal, match: re.Match) -> str:
    """Fixed denominator, shortest decimal input, ties away from zero.

    This deliberately uses the same half-up policy as fixed decimal output;
    Calc's observed downward fixed-fraction ties are not a normative tie rule.
    No fuzzy midpoint exclusion and no arbitrary magnitude cutoff.
    """
    mixed, zeros, denominator_text = match.groups()
    denominator = int(denominator_text)
    numerator = int((number.copy_abs() * denominator).to_integral_value(rounding=ROUND_HALF_UP))
    sign = '-' if number.is_signed() and numerator else ''
    whole = ''
    if mixed:
        integer, numerator = divmod(numerator, denominator)
        whole = str(integer) + ' '
    return sign + whole + str(numerator).zfill(len(zeros)) + '/' + denominator_text


def _render_variable_fraction(value: int | float, match: re.Match) -> str:
    """Nearest rational to the stored value, denominator <= 10**width - 1.

    Fraction.limit_denominator uses continued fractions, bounded here by 999.
    Equal errors prefer the smaller denominator, then the lower magnitude.
    Exact integer arithmetic preserves decisions at adjacent binary64 values.
    """
    numerator_mask, denominator_mask = match.groups()
    nearest = Fraction(abs(value)).limit_denominator(10 ** len(denominator_mask) - 1)
    whole, numerator = divmod(nearest.numerator, nearest.denominator)
    sign = '-' if value < 0 and nearest else ''
    if not numerator:
        return sign + str(whole) + ' ' * (len(numerator_mask) + len(denominator_mask) + 2)
    return (sign + (str(whole) if whole else '') + ' '
            + str(numerator).rjust(len(numerator_mask)) + '/'
            + str(nearest.denominator).ljust(len(denominator_mask)))


def _integer_digits(digits: str, mask: str) -> str:
    """Fill mandatory zeros and alignment spaces without discarding extra digits."""
    digits = digits.lstrip('0')
    result = []
    for placeholder in reversed(mask):
        if digits:
            result.append(digits[-1])
            digits = digits[:-1]
        else:
            result.append('0' if placeholder == '0' else ' ' if placeholder == '?' else '')
    return digits + ''.join(reversed(result))


def _render_fixed(number: Decimal, match: re.Match) -> str:
    integer, fraction, commas, percent = match.groups()
    places = len(fraction or '')
    number = number.scaleb(-3 * len(commas) + (2 if percent else 0))
    number = number.quantize(Decimal(1).scaleb(-places))
    sign = '-' if number < 0 else ''
    digits = format(number.copy_abs(), f'.{places}f')
    whole, _, decimals = digits.partition('.')
    whole = _integer_digits(whole, integer.replace(',', ''))
    if ',' in integer:
        spaces = len(whole) - len(whole.lstrip(' '))
        significant = whole[spaces:]
        groups = [significant[max(0, i - 3):i] for i in range(len(significant), 0, -3)]
        whole = ' ' * spaces + ','.join(reversed(groups))
    if fraction is not None:
        # The explicit decimal separator survives even when every # disappears.
        # MS/ISO describe '.' as displaying the separator. Calc omits it for
        # integral optional-only decimals; that engine difference is intentional.
        last = max([i for i, digit in enumerate(decimals) if digit != '0']
                   + [i for i, token in enumerate(fraction) if token == '0'], default=-1)
        decimals = ''.join(digit if i <= last else (' ' if token == '?' else '')
                           for i, (digit, token) in enumerate(zip(decimals, fraction)))
        whole += '.' + decimals
    return sign + whole + ('%' if percent else '')


def _first_negative_magnitude(conditions: list) -> bool:
    """Calc-compatible negative section classification, beyond sign whitelists.

    MS-XLS delegates display to ISO 29500 18.8.31 but does not specify this edge.
    See LibreOffice include/svl/zformat.hxx IsFirstSubformatRealNegative and
    focused preserved-FORMAT probes in test_xls_numeric_completeness.py.
    """
    first = conditions[0]
    second = conditions[1] if len(conditions) > 1 else None
    return (first is not None and first[1] == 0
            and (second is None or second[1] == 0)
            and ((first[0] == '<' and (second is None or second[0] in ('>', '>=', '=')))
                 or (first[0] == '<=' and (second is None or second[0] == '>'))))


def render_number(value: int | float, code: str, *,
                  display_locale: NumberLocale | None = None,
                  _for_text: bool = False) -> str | None:
    """Render a finite BIFF number without altering its stored Python value.

    Decimal uses the shortest round-trip string, with explicit half-up rounding.
    A private context avoids ambient decimal precision/traps/rounding settings.
    Precision 340 covers finite binary64 fixed output plus percent and 15 places.
    """
    number = Decimal(str(value))
    if not number.is_finite() or number.copy_abs() > _MAX_THRESHOLD:
        return None
    sections = _split_sections(code)
    if sections is None:
        return None
    text_section = ''
    if len(sections) == 4:
        text_section = sections.pop()
        if (_text_parts(text_section) is None
                and _text_parts(text_section, literal_only=True) is None):
            return None
    parsed = []
    conditions = []
    for index, section in enumerate(sections):
        if section == '':
            parsed.append(('', '', ''))
            conditions.append(None)
            continue
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
            parts = _numeric_parts(section, allow_literal=True)
        if parts is None:
            return None
        parsed.append(parts)

    # Validate all sections before selecting on the unrounded stored value.
    conditional = any(condition is not None for condition in conditions)
    if conditional:
        if conditions[0] is None:
            return None
        if len(parsed) == 1 and parsed[0][1] != 'General':
            return None
        # With three numeric sections an omitted second predicate is <0.
        if len(parsed) == 3 and conditions[1] is None:
            conditions[1] = ('<', Decimal(0))
        if _for_text:
            return ''  # Validate syntax, not arbitrary -1/0/1 branch matches.
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
            selected = 0  # Two sign sections include zero in the positive arm.
        if value < 0 and (selected > 0 or _first_negative_magnitude(conditions)):
            value = abs(value)
    else:
        # Route on the stored value, before rounding. Both signed zeros use zero.
        selected = 1 if value < 0 and len(parsed) > 1 else (
            2 if value == 0 and len(parsed) == 3 else 0
        )
        if selected == 1:
            value = abs(value)
    prefix, core, suffix = parsed[selected]

    def attach(text: str) -> str:
        # Translate only generated numeric punctuation, never authored literals.
        if display_locale is not None:
            text = display_locale.localize(text)
        return _with_affixes(text, prefix, suffix)

    if core == 'General':
        # Width-independent whole-number subset. Larger General displays can
        # switch to scientific notation; retain their existing raw projection.
        if abs(value) < 100_000_000_000 and value == int(value):
            return attach(str(int(value)))
        return attach(str(value))
    fixed = _FIXED.fullmatch(core)
    scientific = _SCIENTIFIC.fullmatch(core)
    fraction_format = _FRACTION.fullmatch(core)
    variable_fraction = _VARIABLE_FRACTION.fullmatch(core)
    with localcontext(Context(prec=340, rounding=ROUND_HALF_UP)):
        number = Decimal(str(value))
        if not number.is_finite():
            return None
        if not core:  # Empty section or explicit literal-only third section.
            return prefix
        if variable_fraction is not None:
            return attach(_render_variable_fraction(value, variable_fraction))
        if fraction_format is not None:
            text = _render_fraction(number, fraction_format)
            return attach(text)
        if fixed is not None:
            return attach(_render_fixed(number, fixed))
        fraction, letter, sign, zeros = scientific.groups()
        places = len(fraction or '')
        mantissa, exponent = format(number, f'.{places}E').split('E')
        power = int(exponent) if number else 0
        if not number:
            mantissa = format(Decimal(0), f'.{places}f')
        exponent_sign = '-' if power < 0 else ('+' if sign == '+' else '')
        text = mantissa + letter + exponent_sign + str(abs(power)).zfill(len(zeros))
        return attach(text)


def hides_text(code: str) -> bool:
    """Only a validated format with an empty fourth section.

    Validate every numeric branch; a blank text section must not legitimize
    unsupported syntax elsewhere. The bounded renderer never executes fields.
    """
    sections = _split_sections(code)
    return (sections is not None and len(sections) == 4 and sections[-1] == ''
            and all(render_number(value, code, _for_text=True) is not None for value in (-1, 0, 1)))


def text_affixes(code: str) -> tuple[str, str] | None:
    """Return affixes only for a fully validated ordinary four-section mask.

    Validate numeric syntax independently of whether sample values match any
    conditions; numeric section routing never changes the retained string.
    The caller charges expansion before concatenating the retained string.
    """
    sections = _split_sections(code)
    if sections is None or len(sections) != 4:
        return None
    parts = _text_parts(sections[-1])
    if parts is None or not all(render_number(value, code, _for_text=True) is not None
                                for value in (-1, 0, 1)):
        return None
    return parts


def text_literal(code: str) -> str | None:
    """A bounded literal-only fourth section in a validated ordinary format."""
    sections = _split_sections(code)
    if sections is None or len(sections) != 4:
        return None
    parts = _text_parts(sections[-1], literal_only=True)
    if parts is None or not all(render_number(value, code, _for_text=True) is not None
                                for value in (-1, 0, 1)):
        return None
    return parts[0]
