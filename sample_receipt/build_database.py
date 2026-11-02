"""Prepare public receipt images for human review in an isolated SQLite database."""

import hashlib
import shutil
from pathlib import Path

from analytics.export import export_verified_data
from spending.database import ROOT, connect, initialize
from spending.ocr_engine import RapidOCREngine
from spending.ocr_service import recognise_receipt

SAMPLE_DIR = ROOT / 'sample_receipt'
SAMPLE_DATABASE = SAMPLE_DIR / 'sample_spending.db'
SAMPLE_UPLOADS = SAMPLE_DIR / 'uploads'
IMAGES = ('morrisons.png', 'tesco1.png', 'tesco2.jpg')


def build_sample_database(path=SAMPLE_DATABASE, upload_dir=SAMPLE_UPLOADS):
    """Reset the public sample database, copy images and run OCR once per image."""
    path, upload_dir = Path(path), Path(upload_dir)
    path.unlink(missing_ok=True)
    shutil.rmtree(upload_dir, ignore_errors=True)
    upload_dir.mkdir(parents=True)
    initialize(path)
    receipt_ids = []
    with connect(path) as db:
        for filename in IMAGES:
            source = SAMPLE_DIR / filename
            shutil.copy2(source, upload_dir / filename)
            receipt_ids.append(db.execute(
                "INSERT INTO Receipt(source_path, file_sha256, source_type, status) VALUES (?, ?, 'upload', 'pending')",
                (filename, hashlib.sha256(source.read_bytes()).hexdigest()),
            ).lastrowid)
    engine = RapidOCREngine()
    for receipt_id in receipt_ids:
        recognise_receipt(path, upload_dir, receipt_id, engine)
    return path


def main():
    database = build_sample_database()
    paths = export_verified_data(database, SAMPLE_DIR / 'analytics')
    print(f'Prepared {database} for human review and wrote {len(paths)} analysis tables.')


if __name__ == '__main__':
    main()
