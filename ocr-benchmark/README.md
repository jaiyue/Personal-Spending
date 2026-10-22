# OCR Engine Benchmark

This folder keeps the OCR engine comparison separate from the application. It
contains three receipt image samples, a benchmark script, and pinned Python
dependencies. The script runs the project's current Tesseract preprocessing
pipeline alongside RapidOCR and PaddleOCR on the same source images.

## Run

Install Tesseract and its English language data as described in the [OCR guide](../docs/ocr.md).
Use a separate virtual environment so benchmark packages do not change the
application environment:

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
