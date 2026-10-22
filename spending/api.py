"""Local grocery receipt API: upload documents and inspect pending records."""

from contextlib import asynccontextmanager, closing
import hashlib
import logging
import os
from pathlib import Path
import sqlite3
import tempfile
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, Path as PathParam, Query, Response, UploadFile
from pydantic import BaseModel
from fastapi.responses import JSONResponse

from spending.database import DEFAULT_DATABASE, ROOT, connect, initialize
from spending.uploads import upload_format, validate_document
from spending.ocr_engine import LocalOCREngine
from spending.ocr_service import latest_ocr, recognise_receipt

logger = logging.getLogger(__name__)
ReceiptStatus = Literal['pending', 'processing', 'needs_review', 'verified', 'failed']


class ReceiptSummary(BaseModel):
    id: int
    supermarket_id: int | None
    purchase_date: str | None
    currency: str
    total_minor: int | None
    discount_minor: int
    adjustment_minor: int
    source_path: str | None
    file_sha256: str | None
    source_type: Literal['upload', 'camera', 'manual']
    status: ReceiptStatus
    created_at: str


class ReceiptItem(BaseModel):
    id: int
    receipt_id: int
    line_number: int
    product_id: int | None
    category_id: int | None
    raw_description: str
    quantity: float
    unit_price_minor: int | None
    discount_minor: int
    line_total_minor: int


class ReceiptDetail(ReceiptSummary):
    items: list[ReceiptItem]


class ReceiptPage(BaseModel):
    items: list[ReceiptSummary]
    total: int
    limit: int
    offset: int


class Health(BaseModel):
    status: Literal['ok']
    database: Literal['ok']


class OCRRun(BaseModel):
    id: int
    receipt_id: int
    engine: str
    engine_version: str | None
    status: Literal['pending', 'running', 'succeeded', 'failed']
    confidence: float | None
    error_message: str | None
    started_at: str
    completed_at: str | None
    output: dict | None


def create_app(
    database_path: Path | None = None,
    upload_dir: Path | None = None,
    max_upload_bytes: int | None = None,
    ocr_engine=None,
) -> FastAPI:
    """Create an isolated app; filesystem/database setup happens at startup."""
    database_path = Path(database_path or os.getenv('GROCERY_DATABASE_PATH', DEFAULT_DATABASE)).resolve()
    upload_dir = Path(upload_dir or os.getenv('GROCERY_UPLOAD_DIR', ROOT / 'data' / 'uploads')).resolve()
    if max_upload_bytes is None:
        max_upload_bytes = int(os.getenv('GROCERY_MAX_UPLOAD_BYTES', 10 * 1024 * 1024))
    if max_upload_bytes <= 0:
        raise ValueError('GROCERY_MAX_UPLOAD_BYTES must be positive')
    ocr_engine = ocr_engine if ocr_engine is not None else LocalOCREngine()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        initialize(database_path)
        upload_dir.mkdir(parents=True, exist_ok=True)
        yield

    app = FastAPI(
        title='Grocery Receipt API', version='0.2.0', lifespan=lifespan,
        description='Local grocery receipt uploads, OCR, provisional extraction and queries.',
    )

    @app.exception_handler(sqlite3.Error)
    async def database_error_handler(request, error):
        logger.error('Receipt query failed', exc_info=error)
        return JSONResponse(status_code=503, content={'detail': 'The database is unavailable.'})

    @app.get('/health', response_model=Health, tags=['Health'])
    def health():
        try:
            with closing(connect(database_path)) as db:
                db.execute('SELECT id FROM Receipt LIMIT 1').fetchone()
        except sqlite3.Error as error:
            raise HTTPException(503, 'The database is unavailable.') from error
        return {'status': 'ok', 'database': 'ok'}

    @app.post('/receipts', status_code=201, response_model=ReceiptSummary, tags=['Receipts'])
    def upload_receipt(response: Response, file: Annotated[UploadFile, File()]):
        suffix, format_name = upload_format(file.filename, file.content_type)
        temporary_path = None
        final_path = None
        committed = False
        try:
            digest = hashlib.sha256()
            size = 0
            with tempfile.NamedTemporaryFile(dir=upload_dir, suffix='.part', delete=False) as target:
                temporary_path = Path(target.name)
                while chunk := file.file.read(64 * 1024):
                    size += len(chunk)
                    if size > max_upload_bytes:
                        raise HTTPException(413, f'Receipt files must be at most {max_upload_bytes} bytes.')
                    digest.update(chunk)
                    target.write(chunk)
            if size == 0:
                raise HTTPException(422, 'The receipt file is empty.')
            validate_document(temporary_path, format_name)
            storage_name = f'{uuid4().hex}{suffix}'
            final_path = upload_dir / storage_name
            with closing(connect(database_path)) as db:
                try:
                    with db:
                        cursor = db.execute(
                            "INSERT INTO Receipt(source_path, file_sha256, source_type, status) "
                            "VALUES (?, ?, 'upload', 'pending')",
                            (storage_name, digest.hexdigest()),
                        )
                        receipt = dict(db.execute('SELECT * FROM Receipt WHERE id = ?', (cursor.lastrowid,)).fetchone())
                        temporary_path.replace(final_path)
                except sqlite3.IntegrityError:
                    existing = db.execute('SELECT id FROM Receipt WHERE file_sha256 = ?', (digest.hexdigest(),)).fetchone()
                    if existing:
                        raise HTTPException(409, {
                            'message': 'This receipt file has already been uploaded.',
                            'receipt_id': existing['id'],
                        })
                    raise
            committed = True
            response.headers['Location'] = f"/receipts/{receipt['id']}"
            return receipt
        except (OSError, sqlite3.Error) as error:
            logger.exception('Receipt upload could not be saved')
            raise HTTPException(503, 'The receipt could not be saved. Please try again.') from error
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            if not committed and final_path is not None:
                final_path.unlink(missing_ok=True)

    @app.get('/receipts', response_model=ReceiptPage, tags=['Receipts'])
    def list_receipts(
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
        offset: Annotated[int, Query(ge=0)] = 0,
        status: Annotated[ReceiptStatus | None, Query()] = None,
    ):
        where = ' WHERE status = ?' if status else ''
        parameters = (status,) if status else ()
        with closing(connect(database_path)) as db:
            # A read transaction keeps count and page consistent with each other.
            db.execute('BEGIN')
            total = db.execute('SELECT count(*) FROM Receipt' + where, parameters).fetchone()[0]
            rows = db.execute(
                'SELECT * FROM Receipt' + where + ' ORDER BY id DESC LIMIT ? OFFSET ?',
                (*parameters, limit, offset),
            ).fetchall()
        return {'items': [dict(row) for row in rows], 'total': total, 'limit': limit, 'offset': offset}

    @app.get('/receipts/{receipt_id}', response_model=ReceiptDetail, tags=['Receipts'])
    def get_receipt(receipt_id: Annotated[int, PathParam(ge=1)]):
        with closing(connect(database_path)) as db:
            db.execute('BEGIN')
            row = db.execute('SELECT * FROM Receipt WHERE id = ?', (receipt_id,)).fetchone()
            if row is None:
                raise HTTPException(404, 'Receipt not found.')
            items = db.execute(
                'SELECT * FROM ReceiptItem WHERE receipt_id = ? ORDER BY line_number',
                (receipt_id,),
            ).fetchall()
        return {**dict(row), 'items': [dict(item) for item in items]}

    @app.post('/receipts/{receipt_id}/ocr', response_model=OCRRun, tags=['OCR'])
    def start_ocr(receipt_id: Annotated[int, PathParam(ge=1)]):
        """Recognise a pending/failed receipt synchronously; leave results for review."""
        return recognise_receipt(database_path, upload_dir, receipt_id, ocr_engine)

    @app.get('/receipts/{receipt_id}/ocr', response_model=OCRRun, tags=['OCR'])
    def get_ocr(receipt_id: Annotated[int, PathParam(ge=1)]):
        """Retrieve the latest OCR attempt, including failure details and raw text."""
        return latest_ocr(database_path, receipt_id)

    return app


app = create_app()
