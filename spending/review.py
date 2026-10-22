"""Manual receipt review with an append-only correction audit trail."""

import json
import re
from pathlib import Path
from contextlib import closing

from fastapi import HTTPException

from spending.database import connect

NOW = "strftime('%Y-%m-%dT%H:%M:%fZ','now')"
CURRENCY = re.compile(r'^[A-Z]{3}$')


def _value(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True) if value is not None else None


def _items(db, receipt_id: int):
    return [dict(row) for row in db.execute(
        'SELECT raw_description, quantity, unit_price_minor, discount_minor, line_total_minor '
        'FROM ReceiptItem WHERE receipt_id=? ORDER BY line_number', (receipt_id,),
    )]


def _audit(db, receipt_id: int, field_name: str, original, corrected, corrected_by: str | None, ocr_run_id: int | None):
    db.execute(
        'INSERT INTO correction_audit(receipt_id, ocr_run_id, field_name, original_value, corrected_value, corrected_by) '
        'VALUES (?, ?, ?, ?, ?, ?)',
        (receipt_id, ocr_run_id, field_name, _value(original), _value(corrected), corrected_by),
    )


def correct_receipt(database_path: Path, receipt_id: int, changes: dict, corrected_by: str | None):
    """Apply a reviewed field/item replacement and write only actual changes."""
    fields = set(changes)
    fields.discard('corrected_by')
    if not fields:
        raise HTTPException(422, 'Provide at least one field or an item list to correct.')
    with closing(connect(database_path)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        receipt = db.execute('SELECT * FROM Receipt WHERE id=?', (receipt_id,)).fetchone()
        if receipt is None:
            raise HTTPException(404, 'Receipt not found.')
        if receipt['status'] != 'needs_review':
            raise HTTPException(409, 'Only receipts awaiting review can be corrected.')
        ocr = db.execute(
            'SELECT id FROM ocr_runs WHERE receipt_id=? ORDER BY id DESC LIMIT 1', (receipt_id,)
        ).fetchone()
        ocr_run_id = ocr['id'] if ocr else None
        updates = {}

        if 'supermarket_name' in fields:
            name = changes['supermarket_name']
            if name is not None:
                name = name.strip()
                if not name:
                    raise HTTPException(422, 'Supermarket name cannot be blank.')
                store = db.execute(
                    "SELECT id, name FROM Supermarket WHERE name=? COLLATE NOCASE AND location=''", (name,)
                ).fetchone()
                supermarket_id = store['id'] if store else db.execute(
                    'INSERT INTO Supermarket(name) VALUES (?)', (name,)
                ).lastrowid
            else:
                supermarket_id = None
            if supermarket_id != receipt['supermarket_id']:
                original = db.execute('SELECT name FROM Supermarket WHERE id=?', (receipt['supermarket_id'],)).fetchone()
                _audit(db, receipt_id, 'supermarket_name', original['name'] if original else None, name, corrected_by, ocr_run_id)
                updates['supermarket_id'] = supermarket_id

        for field in ('purchase_date', 'total_minor', 'discount_minor', 'adjustment_minor'):
            if field in fields and changes[field] != receipt[field]:
                _audit(db, receipt_id, field, receipt[field], changes[field], corrected_by, ocr_run_id)
                updates[field] = changes[field]

        if 'currency' in fields:
            currency = changes['currency']
            if currency is None or not CURRENCY.fullmatch(currency):
                raise HTTPException(422, 'Currency must be a three-letter uppercase code.')
            if currency != receipt['currency']:
                _audit(db, receipt_id, 'currency', receipt['currency'], currency, corrected_by, ocr_run_id)
                updates['currency'] = currency

        if updates:
            assignments = ', '.join(f'{name}=?' for name in updates)
            db.execute(f'UPDATE Receipt SET {assignments} WHERE id=?', (*updates.values(), receipt_id))

        if 'items' in fields:
            items = changes['items']
            if items is None:
                raise HTTPException(422, 'Items must be an array when supplied.')
            original_items = _items(db, receipt_id)
            normalised = []
            for item in items:
                description = item['raw_description'].strip()
                if not description:
                    raise HTTPException(422, 'Item description cannot be blank.')
                normalised.append({
                    'raw_description': description,
                    'quantity': item['quantity'],
                    'unit_price_minor': item.get('unit_price_minor'),
                    'discount_minor': item.get('discount_minor', 0),
                    'line_total_minor': item['line_total_minor'],
                })
            if normalised != original_items:
                _audit(db, receipt_id, 'items', original_items, normalised, corrected_by, ocr_run_id)
                db.execute('DELETE FROM ReceiptItem WHERE receipt_id=?', (receipt_id,))
                for line_number, item in enumerate(normalised, start=1):
                    db.execute(
                        'INSERT INTO ReceiptItem(receipt_id, line_number, raw_description, quantity, unit_price_minor, discount_minor, line_total_minor) '
                        'VALUES (?, ?, ?, ?, ?, ?, ?)',
                        (receipt_id, line_number, item['raw_description'], item['quantity'], item['unit_price_minor'], item['discount_minor'], item['line_total_minor']),
                    )
        row = db.execute('SELECT * FROM Receipt WHERE id=?', (receipt_id,)).fetchone()
        items = [dict(item) for item in db.execute('SELECT * FROM ReceiptItem WHERE receipt_id=? ORDER BY line_number', (receipt_id,))]
    return {**dict(row), 'items': items}


def verify_receipt(database_path: Path, receipt_id: int, corrected_by: str | None):
    with closing(connect(database_path)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        receipt = db.execute('SELECT * FROM Receipt WHERE id=?', (receipt_id,)).fetchone()
        if receipt is None:
            raise HTTPException(404, 'Receipt not found.')
        if receipt['status'] != 'needs_review':
            raise HTTPException(409, 'Only receipts awaiting review can be verified.')
        reconciliation = db.execute(
            'SELECT item_count, difference_minor FROM v_receipt_reconciliation WHERE receipt_id=?', (receipt_id,)
        ).fetchone()
        if receipt['supermarket_id'] is None or receipt['purchase_date'] is None or receipt['total_minor'] is None:
            raise HTTPException(422, 'A supermarket, purchase date and total are required before verification.')
        if reconciliation['item_count'] == 0 or reconciliation['difference_minor'] != 0:
            raise HTTPException(422, 'Receipt items must reconcile with the receipt total before verification.')
        ocr = db.execute('SELECT id FROM ocr_runs WHERE receipt_id=? ORDER BY id DESC LIMIT 1', (receipt_id,)).fetchone()
        _audit(db, receipt_id, 'status', 'needs_review', 'verified', corrected_by, ocr['id'] if ocr else None)
        db.execute("UPDATE Receipt SET status='verified' WHERE id=?", (receipt_id,))
        row = db.execute('SELECT * FROM Receipt WHERE id=?', (receipt_id,)).fetchone()
        items = [dict(item) for item in db.execute('SELECT * FROM ReceiptItem WHERE receipt_id=? ORDER BY line_number', (receipt_id,))]
    return {**dict(row), 'items': items}
