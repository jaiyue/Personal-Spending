# Public sample receipts

These three images are approved by the repository owner for public project,
testing and portfolio use. They are kept separate from personal receipt data.

Run `python -m sample_receipt.build_database` from the repository root to reset
`sample_spending.db`, copy images into `uploads/`, run RapidOCR and write
`analytics/*.csv`. Every image stops at `needs_review`; use the sample frontend
to correct and Verify only the grocery receipts you approve.

Start the isolated sample API and desktop page after preparation:

```bash
GROCERY_DATABASE_PATH=sample_receipt/sample_spending.db GROCERY_UPLOAD_DIR=sample_receipt/uploads python -m uvicorn spending.api:app --port 8001
cd desktop && VITE_API_BASE=http://127.0.0.1:8001 npm run dev
```

After Verify, refresh the public CSV files with:

```bash
python -m analytics.export --database sample_receipt/sample_spending.db --output sample_receipt/analytics
```

| File | Store | Treatment |
|---|---|---|
| `morrisons.png` | Morrisons, Holloway | OCR sample; needs human review before grocery verification. |
| `tesco2.jpg` | Tesco, Middlesbrough Coulby Newham Extra | OCR sample; needs a reviewer to supply its missing date before verification. |
| `tesco1.png` | Tesco, Cradley Heath Extra | Clothing OCR sample; keep it unverified or delete it because this project reports grocery only. |

The builder writes only this folder's database and CSV files. It does not access
or change `data/spending.db`.
