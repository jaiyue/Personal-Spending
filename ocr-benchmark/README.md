# OCR Engine Benchmark

This folder keeps the OCR engine comparison separate from the application. It
contains three receipt image samples, a benchmark script, and pinned Python
dependencies. The script runs Tesseract, RapidOCR and PaddleOCR on the same
source images. RapidOCR is the application OCR engine.

## Run

Use a separate virtual environment so benchmark packages do not change the
application environment. Tesseract and its English language data are required
only when including Tesseract in this benchmark; they are not application
dependencies.

```bash
python3 -m venv .venv-ocr-benchmark
source .venv-ocr-benchmark/bin/activate
python -m pip install -r ocr-benchmark/requirements.txt
PADDLE_PDX_CACHE_HOME=ocr-benchmark/.model-cache python ocr-benchmark/benchmark_ocr.py
deactivate
```

Run from the repository root. With no image arguments, the script processes all
three files in `ocr-benchmark/images/`. To run a different set, pass image paths:

```bash
PADDLE_PDX_CACHE_HOME=ocr-benchmark/.model-cache \
  python ocr-benchmark/benchmark_ocr.py path/to/receipt-a.jpg path/to/receipt-b.png
```

The JSON report is written to `ocr-benchmark/results.json` by default. Use
`--output path/to/results.json` to select another location. Results contain the
recognised receipt text, so the default report and model cache are ignored by
Git. PaddleOCR downloads model files on first use.

## What the script records

For each image and engine, it records raw recognized lines, confidence where
available, per-image processing time, and initialization time. It also records
package/runtime versions and image dimensions and SHA-256 hashes. It does not
score, rank, or correct the OCR output. Confidence values use engine-specific
scales and should not be compared directly as accuracy scores.

The three samples are `template-tesco-1-screenshot-1.png`, `3hfst3yj1nsb1.jpg`,
and `1792657121565.jpg`. Their source copies remain in `receipt-image/`.

## Results from the three sample receipts

The checked run used Tesseract 5.5.0, RapidOCR 3.10.0, and PaddleOCR 3.7.0.
The original images were visually checked for shop name, item text, item prices,
discounts, totals and payment values. This is a qualitative result for three
examples, not a measured accuracy benchmark.

| Engine | Average recognition time | Observed result | Suitable use |
|---|---:|---|---|
| Tesseract | 2.815 s | Correct totals and most text on the clean 325 × 872 Tesco screenshot. On the Tesco phone photo it produced extensive noise; on the Lidl photo it read some values but mixed in noise and missed item details. | Lightweight fallback and clean screenshots. |
| RapidOCR | 1.524 s | Read the key fields on all three images, including Tesco £11.70 and Lidl £19.77 totals, discounts and most item lines. It read one Tesco logo as `TESSO`. | Default engine for uploaded receipt photos. |
| PaddleOCR | 38.806 s | Read the key fields and most lines on all three images, close to RapidOCR. It missed or slightly altered some shop-logo text, such as Lidl. | Optional asynchronous review where slower processing is acceptable. |

RapidOCR was both the fastest and the most consistent engine for these samples.
PaddleOCR produced similarly useful receipt text but required about 39 seconds
per image on average, including about 51–53 seconds for the two phone photos.
Tesseract remains useful for clean images, but the two photographed receipts
show that it needs stronger image preparation before it can be trusted as the
only automatic extraction path.

The JSON confidence values are not used to select an engine because each engine
calculates confidence differently. To measure accuracy reproducibly, create
human-verified reference text and structured fields for a larger set of receipt
images, then calculate field-level accuracy from the generated JSON reports.
