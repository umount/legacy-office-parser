"""Extract binary Office documents without a running office suite."""
from .api import parse, parse_doc, parse_ppt, parse_xls, parse_rtf, parse_odt, parse_ods, parse_odp
from .errors import (ParseError, InvalidDocumentError, UnsupportedFormatError,
                     EncryptedDocumentError, LimitExceededError)
from .limits import Limits
from .models import Document, Paragraph, Table, Cell, Slide, SpreadsheetCell, CellRange, Sheet

__version__ = '0.2.0'
__all__ = ['parse_xls', 'parse_rtf', 'parse_odt', 'parse_ods', 'parse_odp',
           'SpreadsheetCell', 'CellRange', 'Sheet', 'parse', 'parse_doc', 'parse_ppt', 'Limits', 'Document', 'Paragraph',
           'Table', 'Cell', 'Slide', 'ParseError', 'InvalidDocumentError',
           'UnsupportedFormatError', 'EncryptedDocumentError', 'LimitExceededError']
