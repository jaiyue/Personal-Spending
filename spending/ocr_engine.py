"""Local RapidOCR image recognition and per-page PDF text extraction."""

from contextlib import closing
from dataclasses import asdict, dataclass
from importlib.metadata import PackageNotFoundError, version
from math import ceil, isqrt
import os
from pathlib import Path
from threading import Lock

from PIL import Image, ImageOps
from pypdf import PdfReader
from pypdf.errors import PyPdfError
import pypdfium2 as pdfium

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


class RapidOCREngine:
    """Recognise receipt images locally with RapidOCR."""

    name = 'rapidocr+pdf-text'

    def __init__(self, recognizer=None):
        self.recognizer = recognizer
        self.max_pages = int(os.getenv('GROCERY_OCR_MAX_PAGES', '10'))
        if self.max_pages <= 0:
            raise ValueError('OCR maximum pages must be positive')

    def _get_recognizer(self):
        if self.recognizer is not None:
            return self.recognizer
        try:
            from rapidocr import RapidOCR
        except ImportError as error:
            raise OCRFailure('RapidOCR is not installed; install the application dependencies.', 503) from error
        try:
            self.recognizer = RapidOCR()
        except Exception as error:
            raise OCRFailure('RapidOCR could not be initialised; check its model files.', 503) from error
        return self.recognizer

    def _image(self, image: Image.Image, page_number: int) -> OCRPage:
        if image.width * image.height > MAX_PIXELS:
            raise OCRFailure('The image exceeds the OCR limit of 20 million pixels.')
        with ImageOps.exif_transpose(image) as oriented:
            with oriented.convert('L') as grayscale:
                prepared = ImageOps.autocontrast(grayscale)
        try:
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
            try:
                result = self._get_recognizer()(prepared)
            except OCRFailure:
                raise
            except Exception as error:
                raise OCRFailure('RapidOCR could not process the document; try a clearer receipt.') from error
            texts = list(getattr(result, 'txts', ()) or ())
            scores = list(getattr(result, 'scores', ()) or ())
            lines = [str(text).strip() for text in texts if str(text).strip()]
            confidence_values = [float(score) for score in scores if score is not None]
            confidence = sum(confidence_values) / len(confidence_values) if confidence_values else None
            return OCRPage(page_number, '\n'.join(lines), 'rapidocr', confidence)
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
        try:
            engine_version = version('rapidocr') if any(page.source == 'rapidocr' for page in pages) else None
        except PackageNotFoundError:
            engine_version = None
        return OCRDocument(text, pages, sum(scores) / len(scores) if scores else None, engine_version)
