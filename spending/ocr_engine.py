"""Local RapidOCR image recognition and per-page PDF text extraction."""

from contextlib import closing
from dataclasses import asdict, dataclass
from importlib.metadata import PackageNotFoundError, version
from math import ceil, isqrt
import os
from pathlib import Path
from threading import Lock

import cv2
import numpy as np
from PIL import Image, ImageOps
from pypdf import PdfReader
from pypdf.errors import PyPdfError
import pypdfium2 as pdfium

PDF_LOCK = Lock()
MAX_PIXELS = 20_000_000
MIN_OCR_WIDTH = 800
MAX_UPSCALE = 3
TILE_MIN_HEIGHT = 2200
TILE_ASPECT_RATIO = 1.2
TILE_HEIGHT = 1600
TILE_HORIZONTAL_INSET = 0.15
MIN_RECEIPT_AREA_RATIO = 0.20
MAX_RECEIPT_AREA_RATIO = 0.97


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

    @staticmethod
    def _order_corners(points: np.ndarray) -> np.ndarray:
        """Order quadrilateral corners as top-left, top-right, bottom-right, bottom-left."""
        points = points.astype('float32')
        ordered = np.zeros((4, 2), dtype='float32')
        sums = points.sum(axis=1)
        differences = np.diff(points, axis=1).ravel()
        ordered[0], ordered[2] = points[np.argmin(sums)], points[np.argmax(sums)]
        ordered[1], ordered[3] = points[np.argmin(differences)], points[np.argmax(differences)]
        return ordered

    @classmethod
    def _receipt_corners(cls, image: Image.Image) -> np.ndarray | None:
        """Return a reliable receipt quadrilateral in original-image coordinates."""
        rgb = np.asarray(image.convert('RGB'))
        height, width = rgb.shape[:2]
        scale = min(1.0, 1600 / max(width, height))
        working = cv2.resize(rgb, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1 else rgb
        gray = cv2.cvtColor(working, cv2.COLOR_RGB2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(blurred, 40, 130)
        edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8), iterations=2)
        _, bright = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        candidates = []
        working_area = working.shape[0] * working.shape[1]
        for mask in (edges, bright):
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for contour in contours:
                area_ratio = cv2.contourArea(contour) / working_area
                if not MIN_RECEIPT_AREA_RATIO <= area_ratio <= MAX_RECEIPT_AREA_RATIO:
                    continue
                perimeter = cv2.arcLength(contour, True)
                polygon = cv2.approxPolyDP(contour, 0.025 * perimeter, True)
                if len(polygon) == 4 and cv2.isContourConvex(polygon):
                    candidates.append((area_ratio, polygon.reshape(4, 2)))
        if not candidates:
            return None

        _, corners = max(candidates, key=lambda candidate: candidate[0])
        corners = cls._order_corners(corners / scale)
        top_left, top_right, bottom_right, bottom_left = corners
        target_width = int(max(np.linalg.norm(top_right - top_left), np.linalg.norm(bottom_right - bottom_left)))
        target_height = int(max(np.linalg.norm(bottom_left - top_left), np.linalg.norm(bottom_right - top_right)))
        if target_width < 120 or target_height < 180:
            return None
        return corners

    @classmethod
    def _locate_receipt(cls, image: Image.Image) -> Image.Image:
        """Find a dominant paper quadrilateral and rectify it before OCR.

        An unreliable or near-full-frame contour falls back to the unchanged image.
        """
        corners = cls._receipt_corners(image)
        if corners is None:
            return image
        rgb = np.asarray(image.convert('RGB'))
        top_left, top_right, bottom_right, bottom_left = corners
        target_width = int(max(np.linalg.norm(top_right - top_left), np.linalg.norm(bottom_right - bottom_left)))
        target_height = int(max(np.linalg.norm(bottom_left - top_left), np.linalg.norm(bottom_right - top_right)))
        destination = np.array([
            [0, 0], [target_width - 1, 0],
            [target_width - 1, target_height - 1], [0, target_height - 1],
        ], dtype='float32')
        transform = cv2.getPerspectiveTransform(corners, destination)
        rectified = cv2.warpPerspective(rgb, transform, (target_width, target_height), borderValue=(255, 255, 255))
        return Image.fromarray(rectified)

    @classmethod
    def preview(cls, path: Path) -> Image.Image:
        """Return a colour source preview with the detected OCR boundary marked."""
        try:
            with Image.open(path) as source, ImageOps.exif_transpose(source) as oriented:
                rgb = np.asarray(oriented.convert('RGB'))
                preview = rgb.copy()
                corners = cls._receipt_corners(oriented)
                if corners is not None:
                    points = np.rint(corners).astype(np.int32).reshape((-1, 1, 2))
                    cv2.polylines(preview, [points], True, (255, 255, 255), 12, cv2.LINE_AA)
                    cv2.polylines(preview, [points], True, (0, 0, 0), 5, cv2.LINE_AA)
                return Image.fromarray(preview)
        except (OSError, ValueError) as error:
            raise OCRFailure('The stored receipt document could not be read.') from error

    @staticmethod
    def _tile_boxes(image: Image.Image, enabled: bool, footer_only: bool) -> list[tuple[int, int, int, int]]:
        """Select the full image or a central footer tile for a retry."""
        if not footer_only or not enabled:
            return [(0, 0, image.width, image.height)]
        left = int(image.width * TILE_HORIZONTAL_INSET)
        right = image.width - left
        return [(left, image.height - TILE_HEIGHT, right, image.height)]

    @staticmethod
    def _merge_tile_lines(merged: list[str], lines: list[str]) -> list[str]:
        """Remove only matching boundary rows produced by tile overlap."""
        normalise = lambda value: ' '.join(value.casefold().split())
        limit = min(len(merged), len(lines))
        overlap = 0
        for size in range(1, limit + 1):
            if [normalise(line) for line in merged[-size:]] == [normalise(line) for line in lines[:size]]:
                overlap = size
        return merged + lines[overlap:]

    @staticmethod
    def _visual_lines(texts, boxes) -> list[str]:
        """Rebuild reading order from OCR geometry instead of detector order."""
        try:
            has_geometry = boxes is not None and len(boxes) == len(texts)
        except TypeError:
            has_geometry = False
        if not has_geometry:
            return [str(text).strip() for text in texts if str(text).strip()]
        tokens = []
        slopes = []
        for text, box in zip(texts, boxes):
            value = str(text).strip()
            points = np.asarray(box, dtype=float)
            if not value or points.shape != (4, 2):
                continue
            left, right = float(points[:, 0].min()), float(points[:, 0].max())
            top, bottom = float(points[:, 1].min()), float(points[:, 1].max())
            center_x, center_y = float(points[:, 0].mean()), float(points[:, 1].mean())
            width = max(1.0, right - left)
            edge_slope = float(((points[1, 1] - points[0, 1]) +
                                (points[2, 1] - points[3, 1])) / (2 * width))
            slopes.append(edge_slope)
            tokens.append({
                'text': value, 'left': left, 'right': right, 'top': top,
                'bottom': bottom, 'center_x': center_x, 'center_y': center_y,
                'height': max(1.0, (np.linalg.norm(points[3] - points[0]) +
                                    np.linalg.norm(points[2] - points[1])) / 2),
            })
        if not tokens:
            return []
        page_slope = float(np.median(slopes))
        for token in tokens:
            token['center'] = token['center_y'] - page_slope * token['center_x']
        median_height = float(np.median([token['height'] for token in tokens]))
        rows: list[list[dict]] = []
        for token in sorted(tokens, key=lambda item: (item['center'], item['left'])):
            best_row = None
            best_distance = None
            for row in rows:
                row_center = float(np.median([item['center'] for item in row]))
                distance = abs(token['center'] - row_center)
                if distance <= median_height * 0.45:
                    if best_distance is None or distance < best_distance:
                        best_row, best_distance = row, distance
            if best_row is None:
                rows.append([token])
            else:
                best_row.append(token)
        rows.sort(key=lambda row: float(np.median([item['center'] for item in row])))
        return [' '.join(item['text'] for item in sorted(row, key=lambda item: item['left'])) for row in rows]

    def _image(self, image: Image.Image, page_number: int, footer_only=False) -> OCRPage:
        if image.width * image.height > MAX_PIXELS:
            raise OCRFailure('The image exceeds the OCR limit of 20 million pixels.')
        with ImageOps.exif_transpose(image) as oriented:
            located = self._locate_receipt(oriented)
            try:
                should_tile = located.height >= TILE_MIN_HEIGHT and located.height / located.width >= TILE_ASPECT_RATIO
                with located.convert('RGB') as colour:
                    prepared = ImageOps.autocontrast(colour)
            finally:
                if located is not oriented:
                    located.close()
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
            lines = []
            confidence_values = []
            boxes = self._tile_boxes(prepared, should_tile, footer_only)
            for tile_number, box in enumerate(boxes):
                with prepared.crop(box) as tile:
                    try:
                        # Receipt text is already oriented as a whole image.
                        # Per-box classification can incorrectly rotate short
                        # amounts such as -0.39, so keep every crop as detected.
                        result = self._get_recognizer()(tile, use_cls=False)
                    except OCRFailure:
                        raise
                    except Exception as error:
                        raise OCRFailure('RapidOCR could not process the document; try a clearer receipt.') from error
                texts = list(getattr(result, 'txts', ()) or ())
                tile_lines = self._visual_lines(texts, getattr(result, 'boxes', None))
                if tile_number:
                    seen = {' '.join(line.casefold().split()) for line in lines}
                    tile_lines = [line for line in tile_lines if ' '.join(line.casefold().split()) not in seen]
                lines = self._merge_tile_lines(lines, tile_lines)
                confidence_values.extend(float(score) for score in (getattr(result, 'scores', ()) or ()) if score is not None)
            confidence = sum(confidence_values) / len(confidence_values) if confidence_values else None
            return OCRPage(page_number, '\n'.join(lines), 'rapidocr', confidence)
        finally:
            prepared.close()

    @staticmethod
    def _merge_new_lines(existing: str, supplemental: str) -> str:
        """Append only lines the full-image OCR did not already return."""
        lines = [line for line in existing.splitlines() if line.strip()]
        seen = {' '.join(line.casefold().split()) for line in lines}
        lines.extend(
            line for line in supplemental.splitlines()
            if line.strip() and ' '.join(line.casefold().split()) not in seen
        )
        return '\n'.join(lines)

    def supplement_footer(self, path: Path, document: OCRDocument) -> OCRDocument:
        """Retry the centred footer of a tall image and merge missing OCR rows."""
        if path.suffix.lower() == '.pdf':
            return document
        try:
            with Image.open(path) as image:
                footer = self._image(image, 1, footer_only=True)
        except (OSError, ValueError) as error:
            raise OCRFailure('The stored receipt document could not be read.') from error
        merged = self._merge_new_lines(document.text, footer.text)
        if merged == document.text:
            return document
        page = OCRPage(1, merged, 'rapidocr', footer.confidence or document.confidence)
        return OCRDocument(merged, [page], page.confidence, document.engine_version)

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
