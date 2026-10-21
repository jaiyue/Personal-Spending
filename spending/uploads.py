"""Validation for grocery receipt documents; no OCR is performed here."""

from pathlib import Path
import warnings

from fastapi import HTTPException
from PIL import Image, UnidentifiedImageError
from pypdf import PdfReader
from pypdf.errors import PyPdfError

FORMATS = {
    '.jpg': ('image/jpeg', 'JPEG'),
    '.jpeg': ('image/jpeg', 'JPEG'),
    '.png': ('image/png', 'PNG'),
    '.pdf': ('application/pdf', 'PDF'),
}


def upload_format(filename: str | None, content_type: str | None) -> tuple[str, str]:
    """Check metadata without using the client filename as a storage path."""
    suffix = Path(filename or '').suffix.lower()
    if suffix not in FORMATS:
        raise HTTPException(415, 'Upload a JPG, PNG, or PDF receipt.')
    expected_mime, format_name = FORMATS[suffix]
    if content_type not in (None, 'application/octet-stream', expected_mime):
        raise HTTPException(415, 'The file extension and content type do not match.')
    return ('.jpg' if suffix == '.jpeg' else suffix), format_name


def validate_document(path: Path, expected_format: str) -> None:
    """Reject unreadable/mismatched images and unreadable or encrypted PDFs."""
    if expected_format == 'PDF':
        try:
            with path.open('rb') as source:
                if source.read(5) != b'%PDF-':
                    raise HTTPException(422, 'The uploaded file is not a valid PDF.')
                source.seek(0)
                reader = PdfReader(source, strict=True)
                if reader.is_encrypted:
                    raise HTTPException(422, 'Encrypted PDFs are not supported.')
                if not reader.pages:
                    raise HTTPException(422, 'The PDF must contain at least one page.')
        except (PyPdfError, ValueError, KeyError, IndexError, RecursionError) as error:
            raise HTTPException(422, 'The PDF could not be read.') from error
        return

    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(path) as image:
                if image.format != expected_format:
                    raise HTTPException(422, 'The image does not match its file extension.')
                image.verify()
            # verify() checks structure; load() additionally checks pixel decoding.
            with Image.open(path) as image:
                image.load()
    except (UnidentifiedImageError, OSError, ValueError,
            Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
        raise HTTPException(422, 'The image could not be read.') from error
