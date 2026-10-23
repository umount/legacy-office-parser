"""Explicit numeric separators; never reads or changes the process locale."""
from dataclasses import dataclass
import unicodedata


@dataclass(frozen=True)
class NumberLocale:
    """Display separators for XLS numbers, independent of literals and raw values."""

    decimal: str = '.'
    grouping: str = ','

    def __post_init__(self):
        for value in (self.decimal, self.grouping):
            if not isinstance(value, str):
                raise TypeError('number separators must be strings')
            if (len(value) != 1 or unicodedata.category(value) not in
                    {'Po', 'Pd', 'Zs'} or value in '+-%/;'):
                raise ValueError('number separators must be single punctuation or space characters')
        if self.decimal == self.grouping or self.decimal.isspace():
            raise ValueError('decimal and grouping separators must be distinct; decimal cannot be space')

    def localize(self, numeric: str) -> str:
        """Translate a numeric core only, before attaching authored literals."""
        return numeric.translate(str.maketrans({'.': self.decimal, ',': self.grouping}))


_LOCALES = {
    'en-us': NumberLocale(), 'en-gb': NumberLocale(),
    'ru-ru': NumberLocale(',', '\u00a0'),
    'de-de': NumberLocale(',', '.'),
    'fr-fr': NumberLocale(',', '\u202f'),
}


def resolve_locale(value: str | NumberLocale | None) -> NumberLocale:
    if value is None:
        return _LOCALES['en-us']
    if isinstance(value, NumberLocale):
        return value
    if not isinstance(value, str):
        raise TypeError('display_locale must be a locale name, NumberLocale or None')
    try:
        return _LOCALES[value.lower().replace('_', '-')]
    except KeyError:
        raise ValueError('unsupported display_locale; use NumberLocale for custom separators') from None
