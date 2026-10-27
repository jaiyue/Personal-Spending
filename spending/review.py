"""Manual receipt review with an append-only correction audit trail."""

import json
import re
from pathlib import Path
from contextlib import closing

from fastapi import HTTPException

from spending.database import connect

NOW = "strftime('%Y-%m-%dT%H:%M:%fZ','now')"
CURRENCY = re.compile(r'^[A-Z]{3}$')
PACK_SIZE = re.compile(r'\b(\d+(?:\.\d+)?)\s*(kg|g|ml|l)\b', re.I)
MULTIPACK_SIZE = re.compile(r'\b(\d+)\s*[x×]\s*(\d+(?:\.\d+)?)\s*(kg|g|ml|l)\b', re.I)


def product_details(description: str) -> tuple[str, float | None, str | None]:
    multipack = MULTIPACK_SIZE.search(description)
    match = multipack or PACK_SIZE.search(description)
    if not match:
        return description, None, None
    size = float(multipack[1]) * float(multipack[2]) if multipack else float(match[1])
    unit = (multipack[3] if multipack else match[2]).lower()
    name = (description[:match.start()] + description[match.end():]).strip(' -')
    return name or description, size, unit


def brand_id_for_description(db, description: str) -> int | None:
    """Match the longest known brand at the start of an item description."""
    normalised = re.sub(r'\s+', ' ', description).strip()
    for brand in db.execute('SELECT id, name FROM Brand ORDER BY length(name) DESC, name'):
        if re.match(rf'{re.escape(brand["name"])}(?=\W|$)', normalised, re.I):
            return brand['id']
    return None


def _value(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True) if value is not None else None


def _items(db, receipt_id: int):
    return [dict(row) for row in db.execute(
        'SELECT raw_description, quantity, unit_price_pence, discount_pence, original_pence '
        'FROM ReceiptItem WHERE receipt_id=? ORDER BY line_number', (receipt_id,),
    )]


def _normalise_item(item: dict) -> dict | None:
    """Expose only OCR/reviewer-entered fields, never legacy derived values."""
    original = item.get('original_pence', item.get('original_total_minor', item.get('line_total_minor')))
    if original is None:
        return None
    return {
        'raw_description': item['raw_description'],
        'quantity': item['quantity'],
        'unit_price_pence': item.get('unit_price_pence', item.get('unit_price_minor')),
        'discount_pence': item.get('discount_pence', item.get('discount_minor', 0)),
        'original_pence': original,
    }


def pending_items(db, receipt_id: int) -> list[dict]:
    """Return unverified OCR items, with any saved review replacement applied."""
    correction = db.execute(
        "SELECT corrected_value FROM correction_audit WHERE receipt_id=? AND field_name='items' ORDER BY id DESC LIMIT 1",
        (receipt_id,),
    ).fetchone()
    if correction:
        return [normalised for item in json.loads(correction['corrected_value'])
                if (normalised := _normalise_item(item)) is not None]
    run = db.execute(
        "SELECT raw_output FROM ocr_runs WHERE receipt_id=? AND status='succeeded' ORDER BY id DESC LIMIT 1",
        (receipt_id,),
    ).fetchone()
    if not run or not run['raw_output']:
        return []
    parsed = json.loads(run['raw_output']).get('parsed', {})
    return [normalised for item in parsed.get('items', [])
            if (normalised := _normalise_item(item)) is not None]


def receipt_items_for_response(db, receipt_id: int) -> list[dict]:
    stored = [dict(item) for item in db.execute(
        'SELECT * FROM ReceiptItem WHERE receipt_id=? ORDER BY line_number', (receipt_id,)
    )]
    if stored:
        return stored
    return [
        {'id': -number, 'receipt_id': receipt_id, 'line_number': number,
         'product_id': None, 'category_id': None, **item}
        for number, item in enumerate(pending_items(db, receipt_id), start=1)
    ]


def pending_supermarket(db, receipt_id: int) -> tuple[str | None, str]:
    correction = db.execute(
        "SELECT corrected_value FROM correction_audit WHERE receipt_id=? AND field_name='supermarket_name' ORDER BY id DESC LIMIT 1",
        (receipt_id,),
    ).fetchone()
    if correction:
        return json.loads(correction['corrected_value']), ''
    run = db.execute(
        "SELECT raw_output FROM ocr_runs WHERE receipt_id=? AND status='succeeded' ORDER BY id DESC LIMIT 1",
        (receipt_id,),
    ).fetchone()
    parsed = json.loads(run['raw_output']).get('parsed', {}) if run and run['raw_output'] else {}
    return parsed.get('supermarket_name'), parsed.get('supermarket_location') or ''


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
            original, _ = pending_supermarket(db, receipt_id)
            if name != original:
                _audit(db, receipt_id, 'supermarket_name', original, name, corrected_by, ocr_run_id)

        for field in ('purchase_date', 'total_pence', 'discount_pence', 'voucher_pence', 'adjustment_pence'):
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
            original_items = _items(db, receipt_id) or pending_items(db, receipt_id)
            normalised = []
            for item in items:
                description = item['raw_description'].strip()
                if not description:
                    raise HTTPException(422, 'Item description cannot be blank.')
                normalised.append({
                    'raw_description': description,
                    'quantity': item['quantity'],
                    'unit_price_pence': item.get('unit_price_pence'),
                    'discount_pence': item.get('discount_pence', 0),
                    'original_pence': item['original_pence'],
                })
            if normalised != original_items:
                _audit(db, receipt_id, 'items', original_items, normalised, corrected_by, ocr_run_id)
        row = db.execute('SELECT * FROM Receipt WHERE id=?', (receipt_id,)).fetchone()
        items = receipt_items_for_response(db, receipt_id)
    return {**dict(row), 'items': items}


def verify_receipt(database_path: Path, receipt_id: int, corrected_by: str | None):
    with closing(connect(database_path)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        receipt = db.execute('SELECT * FROM Receipt WHERE id=?', (receipt_id,)).fetchone()
        if receipt is None:
            raise HTTPException(404, 'Receipt not found.')
        if receipt['status'] != 'needs_review':
            raise HTTPException(409, 'Only receipts awaiting review can be verified.')
        items = pending_items(db, receipt_id)
        name, location = pending_supermarket(db, receipt_id)
        if not name or receipt['purchase_date'] is None or receipt['total_pence'] is None:
            raise HTTPException(422, 'A supermarket, purchase date and total are required before verification.')
        expected = sum(item['original_pence'] - item['discount_pence'] for item in items) - receipt['voucher_pence'] + receipt['adjustment_pence']
        if not items or expected != receipt['total_pence']:
            raise HTTPException(422, 'Receipt items must reconcile with the receipt total before verification.')
        store = db.execute('SELECT id FROM Supermarket WHERE name=? COLLATE NOCASE AND location=?', (name, location)).fetchone()
        supermarket_id = store['id'] if store else db.execute(
            'INSERT INTO Supermarket(name, location) VALUES (?, ?)', (name, location)
        ).lastrowid
        for line_number, item in enumerate(items, start=1):
            name, pack_size, pack_unit = product_details(item['raw_description'])
            brand_id = brand_id_for_description(db, name)
            product = db.execute(
                'SELECT id FROM Item WHERE name=? AND pack_size IS ? AND pack_unit IS ?',
                (name, pack_size, pack_unit),
            ).fetchone()
            product_id = product['id'] if product else db.execute(
                'INSERT INTO Item(name, brand_id, pack_size, pack_unit) VALUES (?, ?, ?, ?)',
                (name, brand_id, pack_size, pack_unit),
            ).lastrowid
            db.execute(
                'INSERT INTO ReceiptItem(receipt_id, line_number, product_id, raw_description, quantity, unit_price_pence, discount_pence, original_pence) '
                'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                (receipt_id, line_number, product_id, item['raw_description'], item['quantity'], item['unit_price_pence'],
                 item['discount_pence'], item['original_pence']),
            )
        ocr = db.execute('SELECT id FROM ocr_runs WHERE receipt_id=? ORDER BY id DESC LIMIT 1', (receipt_id,)).fetchone()
        _audit(db, receipt_id, 'status', 'needs_review', 'verified', corrected_by, ocr['id'] if ocr else None)
        db.execute("UPDATE Receipt SET supermarket_id=?, status='verified' WHERE id=?", (supermarket_id, receipt_id))
        row = db.execute('SELECT * FROM Receipt WHERE id=?', (receipt_id,)).fetchone()
        items = receipt_items_for_response(db, receipt_id)
    return {**dict(row), 'items': items}
