"""Refresh committed OCR results for every public receipt-image fixture."""

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from spending.ocr_engine import RapidOCREngine
from spending.receipt_parser import parse_receipt

IMAGE_DIR = ROOT / 'receipt-image'
OUTPUT = Path(__file__).resolve().parent / 'fixtures' / 'receipt_image_ocr.json'


def main():
    engine = RapidOCREngine()
    results = {}
    for path in sorted(IMAGE_DIR.iterdir()):
        if not path.is_file():
            continue
        print(f'OCR {path.name}', flush=True)
        document = engine.extract(path)
        parsed = parse_receipt(document.text)
        gross = sum(item.original_pence for item in parsed.items)
        item_discount = sum(item.discount_pence for item in parsed.items)
        expected = gross - item_discount - parsed.receipt_discount_pence
        results[path.name] = {
            'text': document.text,
            'confidence': document.confidence,
            'parsed': parsed.to_dict(),
            'summary': {
                'store': parsed.supermarket_name,
                'date': parsed.purchase_date,
                'items': len(parsed.items),
                'gross_pence': gross,
                'item_discount_pence': item_discount,
                'voucher_pence': parsed.receipt_discount_pence,
                'total_pence': parsed.total_pence,
                'reconciles': parsed.total_pence is not None and expected == parsed.total_pence,
                'points_only': parsed.total_pence is None and 'PTS' in document.text,
            },
        }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(results, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'Wrote {OUTPUT.relative_to(ROOT)}')


if __name__ == '__main__':
    main()
