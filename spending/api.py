"""Local receipt API: upload documents and inspect pending records."""

from contextlib import asynccontextmanager, closing
from datetime import date
from io import BytesIO
import hashlib
import logging
import os
from pathlib import Path
import sqlite3
import tempfile
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, Path as PathParam, Query, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from fastapi.responses import FileResponse, JSONResponse

from spending.database import DEFAULT_DATABASE, ROOT, connect, initialize
from spending.uploads import upload_format, validate_document
from spending.ocr_engine import RapidOCREngine
from spending.ocr_service import latest_ocr, recognise_receipt
from spending.review import correct_receipt, receipt_items_for_response, verify_receipt

logger = logging.getLogger(__name__)
ReceiptStatus = Literal['pending', 'processing', 'needs_review', 'verified', 'failed']


class ReceiptSummary(BaseModel):
    id: int
    supermarket_id: int | None
    supermarket_name: str | None = None
    expense_category_id: int | None = None
    expense_category_name: str | None = None
    purchase_date: str | None
    currency: str
    total_pence: int | None
    discount_pence: int
    voucher_pence: int
    adjustment_pence: int
    source_path: str | None
    file_sha256: str | None
    source_type: Literal['upload', 'camera', 'manual']
    status: ReceiptStatus
    created_at: str


class ItemDiscount(BaseModel):
    amount_pence: int
    reason: str | None = None
    source_text: str
    promotion_group: str | None = None


class ItemPromotion(BaseModel):
    group: str
    marker_text: str
    advertised_quantity: int | None = None
    advertised_price_pence: int


class ReceiptItem(BaseModel):
    id: int
    receipt_id: int
    line_number: int
    product_id: int | None
    category_id: int | None
    category_name: str | None = None
    category_source: Literal['matched', 'suggested', 'reviewed'] | None = None
    raw_description: str
    quantity: float
    unit_price_pence: int | None
    discount_pence: int
    original_pence: int
    discounts: list[ItemDiscount] = Field(default_factory=list)
    promotions: list[ItemPromotion] = Field(default_factory=list)
    brand_id: int | None = None
    brand_name: str | None = None
    brand_candidate: str | None = None
    brand_source: Literal['matched', 'candidate', 'supermarket'] | None = None


class ReceiptDetail(ReceiptSummary):
    items: list[ReceiptItem]


class ReceiptPage(BaseModel):
    items: list[ReceiptSummary]
    total: int
    limit: int
    offset: int


class DeletedReceipts(BaseModel):
    deleted: int


class Category(BaseModel):
    id: int
    name: str


class ExpenseCategory(Category):
    pass


class MonthlySpending(BaseModel):
    month: str
    currency: str
    receipt_count: int
    total_pence: int


class CategorySpending(BaseModel):
    month: str
    currency: str
    category_id: int | None
    category_name: str
    total_pence: int


class ExpenseCategorySpending(MonthlySpending):
    expense_category_id: int | None
    expense_category_name: str


class SupermarketSpending(MonthlySpending):
    supermarket_id: int
    supermarket_name: str


class BudgetProgress(BaseModel):
    id: int
    month: str
    category_id: int | None
    category_name: str | None
    currency: str
    amount_pence: int
    actual_pence: int
    remaining_pence: int


class ReceiptReconciliation(BaseModel):
    receipt_id: int
    purchase_date: str | None
    supermarket_name: str | None
    currency: str
    status: ReceiptStatus
    total_pence: int | None
    item_count: int
    items_total_pence: int
    expected_total_pence: int
    difference_pence: int | None


class PriceHistory(BaseModel):
    id: int
    product_id: int
    product_name: str
    supermarket_id: int
    supermarket_name: str
    receipt_item_id: int | None
    price_pence: int
    currency: str
    pack_size: float | None
    pack_unit: str | None
    unit_basis: str | None
    unit_price_pence: float | None
    price_type: Literal['regular', 'promotion', 'loyalty']
    source_type: Literal['receipt', 'online', 'manual']
    source_url: str | None
    observed_at: str


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


class ReviewedItem(BaseModel):
    raw_description: str = Field(min_length=1, max_length=500)
    quantity: float = Field(gt=0)
    unit_price_pence: int | None = Field(default=None, ge=0)
    discount_pence: int = Field(default=0, ge=0)
    original_pence: int = Field(ge=0)
    category_id: int | None = Field(default=None, ge=1)
    brand_name: str | None = Field(default=None, max_length=200)
    brand_candidate: str | None = Field(default=None, max_length=200)
    brand_source: Literal['matched', 'candidate', 'supermarket'] | None = None
    discounts: list[ItemDiscount] = Field(default_factory=list)
    promotions: list[ItemPromotion] = Field(default_factory=list)


class ReceiptCorrection(BaseModel):
    supermarket_name: str | None = Field(default=None, max_length=200)
    expense_category_id: int | None = Field(default=None, ge=1)
    purchase_date: date | None = None
    currency: str | None = Field(default=None, pattern=r'^[A-Z]{3}$')
    total_pence: int | None = Field(default=None, ge=0)
    discount_pence: int | None = Field(default=None, ge=0)
    voucher_pence: int | None = Field(default=None, ge=0)
    adjustment_pence: int | None = None
    items: list[ReviewedItem] | None = None
    corrected_by: str | None = Field(default=None, max_length=200)


class VerificationRequest(BaseModel):
    corrected_by: str | None = Field(default=None, max_length=200)


def delete_receipt_record(database_path: Path, upload_dir: Path, receipt_id: int) -> None:
    """Delete a receipt and its derived records, preserving unrelated business data."""
    staged_path = None
    source_path = None
    with closing(connect(database_path)) as db:
        receipt = db.execute('SELECT source_path, status, supermarket_id FROM Receipt WHERE id=?', (receipt_id,)).fetchone()
        if receipt is None:
            raise HTTPException(404, 'Receipt not found.')
        if receipt['status'] == 'processing':
            raise HTTPException(409, 'A receipt being processed cannot be deleted.')
        protected = db.execute(
            'SELECT 1 FROM quality_notes WHERE receipt_id=? OR receipt_item_id IN '
            '(SELECT id FROM ReceiptItem WHERE receipt_id=?) LIMIT 1', (receipt_id, receipt_id),
        ).fetchone() or db.execute(
            'SELECT 1 FROM price_observations WHERE receipt_item_id IN '
            '(SELECT id FROM ReceiptItem WHERE receipt_id=?) LIMIT 1', (receipt_id,),
        ).fetchone()
        if protected:
            raise HTTPException(409, 'This receipt has related quality notes or price observations and cannot be deleted.')
        storage_name = receipt['source_path']
        if storage_name:
            source_path = (upload_dir / storage_name).resolve()
            if not source_path.is_relative_to(upload_dir.resolve()):
                raise HTTPException(422, 'The stored receipt file is outside the upload directory.')
            if source_path.is_file():
                staged_path = upload_dir / f'.deleting-{uuid4().hex}-{source_path.name}'
                try:
                    source_path.replace(staged_path)
                except OSError as error:
                    raise HTTPException(503, 'The receipt file could not be deleted. Please try again.') from error
        try:
            with db:
                db.execute('DELETE FROM correction_audit WHERE receipt_id=?', (receipt_id,))
                db.execute('DELETE FROM ocr_runs WHERE receipt_id=?', (receipt_id,))
                db.execute('DELETE FROM ItemDiscount WHERE receipt_id=?', (receipt_id,))
                db.execute('DELETE FROM ReceiptItemPromotionGroup WHERE receipt_id=?', (receipt_id,))
                db.execute('DELETE FROM PromotionGroup WHERE receipt_id=?', (receipt_id,))
                db.execute('DELETE FROM ReceiptItem WHERE receipt_id=?', (receipt_id,))
                db.execute('DELETE FROM Receipt WHERE id=?', (receipt_id,))
                if receipt['supermarket_id'] is not None:
                    db.execute('DELETE FROM Supermarket WHERE id=? AND NOT EXISTS '
                               '(SELECT 1 FROM Receipt WHERE supermarket_id=?) AND NOT EXISTS '
                               '(SELECT 1 FROM price_observations WHERE supermarket_id=?)',
                               (receipt['supermarket_id'], receipt['supermarket_id'], receipt['supermarket_id']))
        except Exception:
            if staged_path is not None and source_path is not None:
                staged_path.replace(source_path)
            raise
    if staged_path is not None:
        try:
            staged_path.unlink()
        except OSError:
            logger.exception('Deleted receipt record but could not remove staged file %s', staged_path)


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
    ocr_engine = ocr_engine if ocr_engine is not None else RapidOCREngine()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        initialize(database_path)
        upload_dir.mkdir(parents=True, exist_ok=True)
        yield

    app = FastAPI(
        title='Personal Spending Receipt API', version='0.5.0', lifespan=lifespan,
        description='Local receipt uploads, OCR, review, verification and spending queries.',
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r'^https?://(localhost|127\.0\.0\.1):517[3-9]$',
        allow_credentials=False,
        allow_methods=['*'],
        allow_headers=['*'],
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

    @app.get('/categories', response_model=list[Category], tags=['Categories'])
    def list_categories():
        with closing(connect(database_path)) as db:
            return [dict(row) for row in db.execute('SELECT id, name FROM categories ORDER BY name')]

    @app.get('/expense-categories', response_model=list[ExpenseCategory], tags=['Categories'])
    def list_expense_categories():
        with closing(connect(database_path)) as db:
            return [dict(row) for row in db.execute('SELECT id, name FROM ExpenseCategory ORDER BY name')]

    @app.get('/reports/monthly-spending', response_model=list[MonthlySpending], tags=['Reports'])
    def monthly_spending(
        month: Annotated[str | None, Query(pattern=r'^\d{4}-(0[1-9]|1[0-2])$')] = None,
        currency: Annotated[str | None, Query(pattern=r'^[A-Z]{3}$')] = None,
    ):
        clauses, parameters = [], []
        if month:
            clauses.append('month=?')
            parameters.append(month)
        if currency:
            clauses.append('currency=?')
            parameters.append(currency)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ''
        with closing(connect(database_path)) as db:
            rows = db.execute(
                'SELECT month, currency, receipt_count, total_pence FROM v_monthly_spending'
                + where + ' ORDER BY month, currency', parameters,
            ).fetchall()
        return [dict(row) for row in rows]

    @app.get('/reports/category-spending', response_model=list[CategorySpending], tags=['Reports'])
    def category_spending(
        month: Annotated[str | None, Query(pattern=r'^\d{4}-(0[1-9]|1[0-2])$')] = None,
        currency: Annotated[str | None, Query(pattern=r'^[A-Z]{3}$')] = None,
    ):
        clauses, parameters = [], []
        if month:
            clauses.append('month=?')
            parameters.append(month)
        if currency:
            clauses.append('currency=?')
            parameters.append(currency)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ''
        with closing(connect(database_path)) as db:
            rows = db.execute(
                'SELECT month, currency, category_id, category_name, total_pence '
                'FROM v_category_spending' + where + ' ORDER BY month, currency, category_name', parameters,
            ).fetchall()
        return [dict(row) for row in rows]

    @app.get('/reports/expense-category-spending', response_model=list[ExpenseCategorySpending], tags=['Reports'])
    def expense_category_spending(
        month: Annotated[str | None, Query(pattern=r'^\d{4}-(0[1-9]|1[0-2])$')] = None,
        currency: Annotated[str | None, Query(pattern=r'^[A-Z]{3}$')] = None,
    ):
        clauses, parameters = [], []
        if month:
            clauses.append('month=?')
            parameters.append(month)
        if currency:
            clauses.append('currency=?')
            parameters.append(currency)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ''
        with closing(connect(database_path)) as db:
            rows = db.execute(
                'SELECT month, currency, expense_category_id, expense_category_name, receipt_count, total_pence '
                'FROM v_expense_category_spending' + where + ' ORDER BY month, currency, expense_category_name', parameters,
            ).fetchall()
        return [dict(row) for row in rows]

    @app.get('/reports/supermarket-spending', response_model=list[SupermarketSpending], tags=['Reports'])
    def supermarket_spending(
        month: Annotated[str | None, Query(pattern=r'^\d{4}-(0[1-9]|1[0-2])$')] = None,
        currency: Annotated[str | None, Query(pattern=r'^[A-Z]{3}$')] = None,
    ):
        clauses, parameters = [], []
        if month:
            clauses.append('month=?')
            parameters.append(month)
        if currency:
            clauses.append('currency=?')
            parameters.append(currency)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ''
        with closing(connect(database_path)) as db:
            rows = db.execute(
                'SELECT month, currency, supermarket_id, supermarket_name, receipt_count, total_pence '
                'FROM v_supermarket_spending' + where + ' ORDER BY month, currency, supermarket_name', parameters,
            ).fetchall()
        return [dict(row) for row in rows]

    @app.get('/reports/budgets', response_model=list[BudgetProgress], tags=['Reports'])
    def budget_progress(
        month: Annotated[str | None, Query(pattern=r'^\d{4}-(0[1-9]|1[0-2])$')] = None,
        currency: Annotated[str | None, Query(pattern=r'^[A-Z]{3}$')] = None,
    ):
        clauses, parameters = [], []
        if month:
            clauses.append('b.month=?')
            parameters.append(month)
        if currency:
            clauses.append('b.currency=?')
            parameters.append(currency)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ''
        with closing(connect(database_path)) as db:
            rows = db.execute(
                'SELECT b.id, b.month, b.category_id, c.name AS category_name, b.currency, '
                'b.amount_pence, b.actual_pence, b.remaining_pence '
                'FROM v_budget_vs_actual b LEFT JOIN categories c ON c.id=b.category_id'
                + where + ' ORDER BY b.month, b.currency, category_name', parameters,
            ).fetchall()
        return [dict(row) for row in rows]

    @app.get('/reports/reconciliation', response_model=list[ReceiptReconciliation], tags=['Reports'])
    def receipt_reconciliation(
        receipt_id: Annotated[int | None, Query(ge=1)] = None,
        status: Annotated[ReceiptStatus | None, Query()] = None,
    ):
        clauses, parameters = [], []
        if receipt_id:
            clauses.append('v.receipt_id=?')
            parameters.append(receipt_id)
        if status:
            clauses.append('v.status=?')
            parameters.append(status)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ''
        with closing(connect(database_path)) as db:
            rows = db.execute(
                'SELECT v.*, r.purchase_date, s.name AS supermarket_name '
                'FROM v_receipt_reconciliation v JOIN Receipt r ON r.id=v.receipt_id '
                'LEFT JOIN Supermarket s ON s.id=r.supermarket_id'
                + where + ' ORDER BY v.receipt_id DESC', parameters,
            ).fetchall()
        return [dict(row) for row in rows]

    @app.get('/reports/price-history', response_model=list[PriceHistory], tags=['Reports'])
    def price_history(
        product_id: Annotated[int | None, Query(ge=1)] = None,
        supermarket_id: Annotated[int | None, Query(ge=1)] = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 100,
    ):
        clauses, parameters = [], []
        if product_id:
            clauses.append('product_id=?')
            parameters.append(product_id)
        if supermarket_id:
            clauses.append('supermarket_id=?')
            parameters.append(supermarket_id)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ''
        with closing(connect(database_path)) as db:
            rows = db.execute(
                'SELECT id, product_id, product_name, supermarket_id, supermarket_name, receipt_item_id, '
                'price_pence, currency, pack_size, pack_unit, unit_basis, unit_price_pence, '
                'price_type, source_type, source_url, observed_at FROM v_product_price_history'
                + where + ' ORDER BY observed_at DESC, id DESC LIMIT ?', (*parameters, limit),
            ).fetchall()
        return [dict(row) for row in rows]

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
                "SELECT r.*, coalesce(s.name, json_extract((SELECT raw_output FROM ocr_runs "
                "WHERE receipt_id=r.id AND status='succeeded' ORDER BY id DESC LIMIT 1), "
                "'$.parsed.supermarket_name')) AS supermarket_name, e.name AS expense_category_name FROM Receipt r "
                'LEFT JOIN Supermarket s ON s.id=r.supermarket_id'
                ' LEFT JOIN ExpenseCategory e ON e.id=r.expense_category_id'
                + where.replace(' WHERE status', ' WHERE r.status')
                + ' ORDER BY r.purchase_date DESC, r.id DESC LIMIT ? OFFSET ?',
                (*parameters, limit, offset),
            ).fetchall()
        return {'items': [dict(row) for row in rows], 'total': total, 'limit': limit, 'offset': offset}

    @app.get('/receipts/{receipt_id}', response_model=ReceiptDetail, tags=['Receipts'])
    def get_receipt(receipt_id: Annotated[int, PathParam(ge=1)]):
        with closing(connect(database_path)) as db:
            db.execute('BEGIN')
            row = db.execute(
                "SELECT r.*, coalesce(s.name, json_extract((SELECT raw_output FROM ocr_runs "
                "WHERE receipt_id=r.id AND status='succeeded' ORDER BY id DESC LIMIT 1), "
                "'$.parsed.supermarket_name')) AS supermarket_name, e.name AS expense_category_name FROM Receipt r "
                'LEFT JOIN Supermarket s ON s.id=r.supermarket_id '
                'LEFT JOIN ExpenseCategory e ON e.id=r.expense_category_id WHERE r.id=?', (receipt_id,)
            ).fetchone()
            if row is None:
                raise HTTPException(404, 'Receipt not found.')
            items = receipt_items_for_response(db, receipt_id)
        return {**dict(row), 'items': items}

    @app.get('/receipts/{receipt_id}/document', tags=['Receipts'])
    def get_receipt_document(receipt_id: Annotated[int, PathParam(ge=1)]):
        """Return the uploaded receipt file for the local review screen."""
        with closing(connect(database_path)) as db:
            row = db.execute('SELECT source_path FROM Receipt WHERE id=?', (receipt_id,)).fetchone()
        if row is None:
            raise HTTPException(404, 'Receipt not found.')
        if not row['source_path']:
            raise HTTPException(404, 'This receipt has no uploaded document.')

        storage_root = upload_dir.resolve()
        document_path = (upload_dir / row['source_path']).resolve()
        if not document_path.is_relative_to(storage_root):
            raise HTTPException(422, 'The receipt document path is invalid.')
        if not document_path.is_file():
            raise HTTPException(404, 'The receipt document could not be found.')

        media_types = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.pdf': 'application/pdf'}
        media_type = media_types.get(document_path.suffix.lower(), 'application/octet-stream')
        return FileResponse(document_path, media_type=media_type, content_disposition_type='inline')

    @app.get('/receipts/{receipt_id}/ocr-preview', tags=['OCR'])
    def get_receipt_ocr_preview(receipt_id: Annotated[int, PathParam(ge=1)]):
        """Show the colour image and the receipt boundary used before OCR."""
        with closing(connect(database_path)) as db:
            row = db.execute('SELECT source_path FROM Receipt WHERE id=?', (receipt_id,)).fetchone()
        if row is None:
            raise HTTPException(404, 'Receipt not found.')
        if not row['source_path'] or Path(row['source_path']).suffix.lower() == '.pdf':
            raise HTTPException(404, 'An OCR image preview is not available for this receipt.')
        document_path = (upload_dir / row['source_path']).resolve()
        if not document_path.is_relative_to(upload_dir.resolve()) or not document_path.is_file():
            raise HTTPException(404, 'The receipt document could not be found.')
        try:
            with ocr_engine.preview(document_path) as preview:
                output = BytesIO()
                preview.save(output, format='PNG')
        except Exception as error:
            logger.exception('OCR preview could not be generated')
            raise HTTPException(422, 'The OCR preview could not be generated.') from error
        return Response(output.getvalue(), media_type='image/png', headers={'Cache-Control': 'no-store'})

    @app.delete('/receipts/unverified', response_model=DeletedReceipts, tags=['Receipts'])
    def delete_unverified_receipts():
        """Permanently delete pending, failed, and review receipts; preserve verified receipts."""
        with closing(connect(database_path)) as db:
            receipt_ids = [row['id'] for row in db.execute(
                "SELECT id FROM Receipt WHERE status IN ('pending', 'failed', 'needs_review') ORDER BY id"
            )]
        for receipt_id in receipt_ids:
            delete_receipt_record(database_path, upload_dir, receipt_id)
        return {'deleted': len(receipt_ids)}

    @app.delete('/receipts/{receipt_id}', status_code=204, tags=['Receipts'])
    def delete_receipt(receipt_id: Annotated[int, PathParam(ge=1)]):
        """Permanently delete a receipt, its file, OCR data, item lines and audit history."""
        delete_receipt_record(database_path, upload_dir, receipt_id)
        return Response(status_code=204)

    @app.patch('/receipts/{receipt_id}/review', response_model=ReceiptDetail, tags=['Review'])
    def correct_review_receipt(
        receipt_id: Annotated[int, PathParam(ge=1)], correction: ReceiptCorrection,
    ):
        """Correct OCR suggestions while preserving before/after values in the audit log."""
        changes = correction.model_dump(mode='json', exclude_unset=True)
        corrected_by = changes.pop('corrected_by', None)
        return correct_receipt(database_path, receipt_id, changes, corrected_by)

    @app.post('/receipts/{receipt_id}/verify', response_model=ReceiptDetail, tags=['Review'])
    def verify_review_receipt(
        receipt_id: Annotated[int, PathParam(ge=1)], request: VerificationRequest,
    ):
        """Verify a reconciled reviewed receipt so it is included in spending views."""
        return verify_receipt(database_path, receipt_id, request.corrected_by)

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
