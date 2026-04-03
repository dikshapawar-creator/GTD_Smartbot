"""
Custom SQLAlchemy types for SQL Server UTF-16 compatibility.

SQL Server stores NVARCHAR/NTEXT columns in UTF-16 LE.
When pyodbc reads them, the result is sometimes a raw UTF-16 LE byte string
with null bytes between every character (e.g. 'h\x00i\x00').

These TypeDecorators transparently strip null bytes on read so all Python
code receives clean, normal UTF-8 strings.
"""
import json
from sqlalchemy import TypeDecorator, Text, Unicode


def _clean_utf16(v: str) -> str:
    """Strip UTF-16 LE null bytes from a string read from SQL Server."""
    if v and isinstance(v, str) and '\x00' in v:
        try:
            return v.encode('latin1').decode('utf-16-le').rstrip('\x00')
        except Exception:
            return v.replace('\x00', '')
    return v or ''


class CleanText(TypeDecorator):
    """
    A Text column that transparently decodes UTF-16 LE strings on read.
    Use instead of Text/String for any column that may contain user-supplied
    content stored by SQL Server as NVARCHAR/NTEXT.
    """
    impl = Text
    cache_ok = True

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        return _clean_utf16(value)


class CleanUnicode(TypeDecorator):
    """
    A Unicode column that transparently decodes UTF-16 LE strings on read.
    Drop-in replacement for Unicode() in model definitions.
    """
    impl = Unicode
    cache_ok = True

    def __init__(self, length=None, *args, **kwargs):
        super().__init__(length, *args, **kwargs)

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        return _clean_utf16(value)
