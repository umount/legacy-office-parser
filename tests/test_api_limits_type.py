"""Invalid configuration is rejected before source access, never silently defaulted."""
import pytest
from legacy_office_parser import (
    parse, parse_doc, parse_xls, parse_ppt, parse_rtf, parse_odt, parse_ods, parse_odp,
)


@pytest.mark.parametrize('reader', [parse, parse_doc, parse_xls, parse_ppt, parse_rtf,
                                    parse_odt, parse_ods, parse_odp])
@pytest.mark.parametrize('value', [False, True, 0, 1, '', {}, object()])
def test_limits_type_checked_before_open(reader, value):
    with pytest.raises(TypeError, match='limits must be Limits or None'):
        reader('/nonexistent/source-that-must-not-be-opened', limits=value)
