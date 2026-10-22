"""Local image OCR and per-page PDF text/OCR extraction."""

import csv
from contextlib import closing
from dataclasses import asdict, dataclass
from io import BytesIO, StringIO
from math import ceil, isqrt
import os
from pathlib import Path
import subprocess
from threading import Lock

from PIL import Image, ImageOps
from pypdf import PdfReader
from pypdf.errors import PyPdfError
import pypdfium2 as pdfium

# PDFium calls, including object destruction, must not overlap between threads.
PDF_LOCK = Lock()
MAX_PIXELS = 20_000_000
MIN_OCR_WIDTH = 800
MAX_UPSCALE = 3


class OCRFailure(Exception):
    def __init__(self, message: str, status_code=422):
        super().__init__(message)
        self.status_code = status_code


@dataclass
class OCRPage:
    number: int
    text: str
    source: str
    confidence: float | None


@dataclass
class OCRDocument:
    text: str
    pages: list[OCRPage]
    confidence: float | None
    engine_version: str | None = None

    def to_dict(self):
        return asdict(self)


def read_tsv(tsv: str) -> tuple[str, float | None]:
    lines = {}
    confidences = []
    for word in csv.DictReader(StringIO(tsv), delimiter='\t'):
        text = (word.get('text') or '').strip()
        if not text:
            continue
        key = tuple(word.get(name) for name in ('page_num', 'block_num', 'par_num', 'line_num'))
        lines.setdefault(key, []).append(text)
        confidence = float(word.get('conf', '-1'))
        if confidence >= 0:
            confidences.append(min(confidence, 100) / 100)
    text = '\n'.join(' '.join(words) for words in lines.values())
    return text, sum(confidences) / len(confidences) if confidences else None


class LocalOCREngine:
    name = 'tesseract+pdf-text'

    def __init__(self):
        self.command = os.getenv('GROCERY_TESSERACT_CMD', 'tesseract')
        self.language = os.getenv('GROCERY_OCR_LANGUAGE', 'eng')
        self.timeout = float(os.getenv('GROCERY_OCR_TIMEOUT_SECONDS', '60'))
        self.max_pages = int(os.getenv('GROCERY_OCR_MAX_PAGES', '10'))
        if self.timeout <= 0 or self.max_pages <= 0:
            raise ValueError('OCR timeout and maximum pages must be positive')

    def _image(self, image: Image.Image, page_number: int) -> OCRPage:
        if image.width * image.height > MAX_PIXELS:
            raise OCRFailure('The image exceeds the OCR limit of 20 million pixels.')
        with ImageOps.exif_transpose(image) as oriented:
            with oriented.convert('L') as grayscale:
                prepared = ImageOps.autocontrast(grayscale)
        try:
            # Small receipt screenshots benefit from larger glyphs. Preserve
            # aspect ratio, cap the scale, and never exceed the pixel budget.
            scale = min(
                MAX_UPSCALE, ceil(MIN_OCR_WIDTH / prepared.width),
                isqrt(MAX_PIXELS // (prepared.width * prepared.height)),
            )
            if scale > 1:
                enlarged = prepared.resize(
                    (prepared.width * scale, prepared.height * scale),
                    Image.Resampling.LANCZOS,
                )
                prepared.close()
                prepared = enlarged
            with BytesIO() as data:
                prepared.save(data, format='PNG')
                try:
                    process = subprocess.run(
                        [self.command, 'stdin', 'stdout', '-l', self.language, '--psm', '6', 'tsv'],
                        input=data.getvalue(), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        timeout=self.timeout, check=True,
                    )
                except FileNotFoundError as error:
                    raise OCRFailure('Tesseract is not installed or GROCERY_TESSERACT_CMD is invalid.', 503) from error
                except subprocess.TimeoutExpired as error:
                    raise OCRFailure('OCR timed out; try a smaller or clearer receipt.', 504) from error
                except subprocess.CalledProcessError as error:
                    raise OCRFailure('Tesseract could not process the document; check the configured language data.', 503) from error
            text, confidence = read_tsv(process.stdout.decode('utf-8', errors='replace'))
            return OCRPage(page_number, text, 'tesseract', confidence)
        finally:
            prepared.close()

    def extract(self, path: Path) -> OCRDocument:
        pages = []
        try:
            if path.suffix.lower() == '.pdf':
                with path.open('rb') as source:
                    pdf = PdfReader(source, strict=True)
                    if pdf.is_encrypted:
                        raise OCRFailure('Encrypted PDFs cannot be recognised.')
                    if not 0 < len(pdf.pages) <= self.max_pages:
                        raise OCRFailure(f'PDF receipts must contain 1 to {self.max_pages} pages.')
                    for index, page in enumerate(pdf.pages):
                        text = (page.extract_text() or '').strip()
                        if text:
                            pages.append(OCRPage(index + 1, text, 'pdf_text', None))
                            continue
                        with PDF_LOCK:
                            with closing(pdfium.PdfDocument(path)) as rendered:
                                with closing(rendered[index]) as rendered_page:
                                    width, height = rendered_page.get_size()
                                    if width * height * 2.5 ** 2 > MAX_PIXELS:
                                        raise OCRFailure('The rendered PDF page exceeds the OCR pixel limit.')
                                    bitmap = rendered_page.render(scale=2.5)
                                    try:
                                        # Copy pixel data before releasing PDFium objects/lock.
                                        image = bitmap.to_pil().copy()
                                    finally:
                                        bitmap.close()
                        with image:
                            pages.append(self._image(image, index + 1))
            else:
                with Image.open(path) as image:
                    pages.append(self._image(image, 1))
        except OCRFailure:
            raise
        except (OSError, ValueError, PyPdfError, pdfium.PdfiumError) as error:
            raise OCRFailure('The stored receipt document could not be read.') from error
        text = '\n\n'.join(page.text for page in pages).strip()
        if not text:
            raise OCRFailure('No readable text found; upload a clearer receipt.')
        if len(text) > 100_000:
            raise OCRFailure('The document contains too much text for a receipt.')
        scores = [page.confidence for page in pages if page.confidence is not None]
        version = None
        if any(page.source == 'tesseract' for page in pages):
            try:
                version = subprocess.run([self.command, '--version'], capture_output=True,
                                         text=True, timeout=5, check=True).stdout.splitlines()[0]
            except (OSError, subprocess.SubprocessError, IndexError):
                pass
        return OCRDocument(text, pages, sum(scores) / len(scores) if scores else None, version)
