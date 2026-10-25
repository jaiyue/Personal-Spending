"""Persist OCR attempts and provisional grocery records without overwriting review."""

from contextlib import closing
import json
import logging
from pathlib import Path
import sqlite3

from fastapi import HTTPException

from spending.database import connect
from spending.ocr_engine import OCRFailure
from spending.receipt_parser import parse_receipt

logger = logging.getLogger(__name__)
NOW = "strftime('%Y-%m-%dT%H:%M:%fZ','now')"


def run_response(row):
    result = dict(row)
    raw = result.pop('raw_output')
    result['output'] = json.loads(raw) if raw else None
    return result


def latest_ocr(database_path: Path, receipt_id: int):
    with closing(connect(database_path)) as db:
        if not db.execute('SELECT id FROM Receipt WHERE id=?', (receipt_id,)).fetchone():
            raise HTTPException(404, 'Receipt not found.')
        row = db.execute('SELECT * FROM ocr_runs WHERE receipt_id=? ORDER BY id DESC LIMIT 1', (receipt_id,)).fetchone()
    if row is None:
        raise HTTPException(404, 'This receipt has no OCR attempt yet.')
    return run_response(row)


def recognise_receipt(database_path: Path, upload_dir: Path, receipt_id: int, engine):
    # Commit the claim before expensive OCR; other requests can observe processing
    # and the database write lock is not held while OCR is running.
    with closing(connect(database_path)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        receipt = db.execute('SELECT * FROM Receipt WHERE id=?', (receipt_id,)).fetchone()
        if receipt is None:
            raise HTTPException(404, 'Receipt not found.')
        if receipt['status'] not in ('pending', 'failed'):
            raise HTTPException(409, 'Only pending or failed receipts can start OCR; existing review results are preserved.')
        if db.execute('SELECT 1 FROM ReceiptItem WHERE receipt_id=?', (receipt_id,)).fetchone() or db.execute(
            'SELECT 1 FROM correction_audit WHERE receipt_id=?', (receipt_id,),
        ).fetchone():
            raise HTTPException(409, 'This receipt already has items or corrections; OCR will not overwrite them.')
        db.execute("UPDATE Receipt SET status='processing' WHERE id=?", (receipt_id,))
        cursor = db.execute("INSERT INTO ocr_runs(receipt_id, engine, status) VALUES (?, ?, 'running')", (receipt_id, engine.name))
        run_id = cursor.lastrowid
        storage_name = receipt['source_path']

    output = None
    confidence = None
    version = None
    try:
        if not storage_name:
            raise OCRFailure('This receipt has no stored document.')
        document_path = (upload_dir / storage_name).resolve()
        if not document_path.is_relative_to(upload_dir.resolve()) or not document_path.is_file():
            raise OCRFailure('The stored receipt file is missing or outside the upload directory.')
        document = engine.extract(document_path)
        confidence, version = document.confidence, document.engine_version
        parsed = parse_receipt(document.text)
        output = {**document.to_dict(), 'parsed': parsed.to_dict()}
        encoded = json.dumps(output, ensure_ascii=False)
        with closing(connect(database_path)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            current = db.execute('SELECT status FROM Receipt WHERE id=?', (receipt_id,)).fetchone()
            if current is None or current['status'] != 'processing' or db.execute(
                'SELECT 1 FROM ReceiptItem WHERE receipt_id=?', (receipt_id,),
            ).fetchone() or db.execute('SELECT 1 FROM correction_audit WHERE receipt_id=?', (receipt_id,)).fetchone():
                raise OCRFailure('The receipt changed while OCR was running; existing review data was preserved.', 409)
            supermarket_id = None
            if parsed.supermarket_name:
                store = db.execute(
                    "SELECT id FROM Supermarket WHERE name = ? COLLATE NOCASE AND location=''",
                    (parsed.supermarket_name,),
                ).fetchone()
                if store:
                    supermarket_id = store['id']
                else:
                    supermarket_id = db.execute('INSERT INTO Supermarket(name) VALUES (?)', (parsed.supermarket_name,)).lastrowid
            db.execute(
                "UPDATE Receipt SET supermarket_id=?, purchase_date=?, total_minor=?, discount_minor=?, "
                "currency=coalesce(?, currency), status='needs_review' WHERE id=? AND status='processing'",
                (supermarket_id, parsed.purchase_date, parsed.total_minor,
                 sum(item.discount_minor for item in parsed.items), parsed.currency, receipt_id),
            )
            for number, item in enumerate(parsed.items, start=1):
                db.execute(
                    'INSERT INTO ReceiptItem(receipt_id, line_number, raw_description, quantity, unit_price_minor, discount_minor, line_total_minor) '
                    'VALUES (?, ?, ?, ?, ?, ?, ?)',
                    (receipt_id, number, item.raw_description, item.quantity, item.unit_price_minor,
                     item.discount_minor, item.line_total_minor),
                )
            db.execute(
                f"UPDATE ocr_runs SET status='succeeded', raw_output=?, confidence=?, engine_version=?, completed_at={NOW} WHERE id=?",
                (encoded, confidence, version, run_id),
            )
        return latest_ocr(database_path, receipt_id)
    except Exception as error:
        if isinstance(error, OCRFailure):
            message, code = str(error), error.status_code
        elif isinstance(error, sqlite3.Error):
            logger.exception('OCR results could not be saved')
            message, code = 'OCR results could not be saved; please retry.', 503
        else:
            logger.exception('Unexpected OCR failure')
            message, code = 'The document could not be recognised; please retry.', 500
        with closing(connect(database_path)) as db, db:
            db.execute(
                f"UPDATE ocr_runs SET status='failed', error_message=?, raw_output=?, confidence=?, engine_version=?, completed_at={NOW} WHERE id=? AND status='running'",
                (message, json.dumps(output, ensure_ascii=False) if output else None, confidence, version, run_id),
            )
            db.execute("UPDATE Receipt SET status='failed' WHERE id=? AND status='processing'", (receipt_id,))
        raise HTTPException(code, {'message': message, 'ocr_run_id': run_id}) from error
