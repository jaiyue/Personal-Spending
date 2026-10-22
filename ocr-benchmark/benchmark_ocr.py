#!/usr/bin/env python3
"""Run Tesseract, RapidOCR and PaddleOCR on the same receipt images.

Optional engines are loaded from the active Python environment. The JSON output
contains raw OCR lines and timings; this script does not score or rank engines.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import statistics
import sys
import time

from PIL import Image

BENCHMARK_DIR = Path(__file__).resolve().parent
ROOT = BENCHMARK_DIR.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_IMAGES = (
    BENCHMARK_DIR / "images/template-tesco-1-screenshot-1.png",
    BENCHMARK_DIR / "images/3hfst3yj1nsb1.jpg",
    BENCHMARK_DIR / "images/1792657121565.jpg",
)
DEFAULT_OUTPUT = BENCHMARK_DIR / "results.json"


def package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def image_metadata(path: Path) -> dict:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    with Image.open(path) as image:
        width, height = image.size
    try:
        display_path = str(path.resolve().relative_to(ROOT))
    except ValueError:
        display_path = str(path.resolve())
    return {
        "path": display_path,
        "width": width,
        "height": height,
        "sha256": digest,
    }


def scored_lines(texts, scores) -> list[dict]:
    texts = list(texts or [])
    scores = list(scores or [])
    return [
        {
            "text": str(text),
            "confidence": float(scores[index]) if index < len(scores) else None,
        }
        for index, text in enumerate(texts)
        if str(text).strip()
    ]


def mean_confidence(lines: list[dict]) -> float | None:
    scores = [line["confidence"] for line in lines if line["confidence"] is not None]
    return statistics.fmean(scores) if scores else None


def load_engines() -> tuple[dict, dict]:
    engines = {}
    metadata = {}

    start = time.perf_counter()
    try:
        from spending.ocr_engine import LocalOCREngine

        engines["tesseract"] = LocalOCREngine()
        metadata["tesseract"] = {
            "package_version": None,
            "configuration": "Project LocalOCREngine; image orientation, grayscale, autocontrast and small-image upscaling enabled.",
            "initialization_seconds": round(time.perf_counter() - start, 3),
        }
    except Exception as error:  # Keep collecting results from the other engines.
        metadata["tesseract"] = {
            "initialization_seconds": round(time.perf_counter() - start, 3),
            "initialization_error": f"{type(error).__name__}: {error}",
        }

    start = time.perf_counter()
    try:
        from rapidocr import RapidOCR

        engines["rapidocr"] = RapidOCR()
        metadata["rapidocr"] = {
            "package_version": package_version("rapidocr"),
            "runtime_versions": {"onnxruntime": package_version("onnxruntime")},
            "configuration": "RapidOCR defaults; PP-OCR model files are initialized lazily on first image.",
            "initialization_seconds": round(time.perf_counter() - start, 3),
        }
    except Exception as error:
        metadata["rapidocr"] = {
            "package_version": package_version("rapidocr"),
            "runtime_versions": {"onnxruntime": package_version("onnxruntime")},
            "initialization_seconds": round(time.perf_counter() - start, 3),
            "initialization_error": f"{type(error).__name__}: {error}",
        }

    start = time.perf_counter()
    try:
        from paddleocr import PaddleOCR

        engines["paddleocr"] = PaddleOCR(
            lang="en",
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
        )
        metadata["paddleocr"] = {
            "package_version": package_version("paddleocr"),
            "runtime_versions": {"paddlepaddle": package_version("paddlepaddle")},
            "configuration": "PaddleOCR English defaults with document orientation, unwarping and textline orientation disabled.",
            "initialization_seconds": round(time.perf_counter() - start, 3),
        }
    except Exception as error:
        metadata["paddleocr"] = {
            "package_version": package_version("paddleocr"),
            "runtime_versions": {"paddlepaddle": package_version("paddlepaddle")},
            "initialization_seconds": round(time.perf_counter() - start, 3),
            "initialization_error": f"{type(error).__name__}: {error}",
        }

    return engines, metadata


def recognize(engine_name: str, engine, path: Path) -> dict:
    start = time.perf_counter()
    try:
        if engine_name == "tesseract":
            document = engine.extract(path)
            lines = [
                {"text": line, "confidence": None}
                for line in document.text.splitlines()
                if line.strip()
            ]
            return {
                "status": "ok",
                "elapsed_seconds": round(time.perf_counter() - start, 3),
                "engine_version": document.engine_version,
                "confidence": document.confidence,
                "lines": lines,
                "text": document.text,
            }

        if engine_name == "rapidocr":
            result = engine(str(path))
            lines = scored_lines(result.txts, result.scores)
            return {
                "status": "ok",
                "elapsed_seconds": round(time.perf_counter() - start, 3),
                "confidence": mean_confidence(lines),
                "lines": lines,
                "text": "\n".join(line["text"] for line in lines),
                "stage_elapsed_seconds": result.elapse_list,
            }

        result = engine.predict(input=str(path))
        if not result:
            lines = []
        else:
            payload = result[0].json
            payload = payload.get("res", payload)
            lines = scored_lines(payload.get("rec_texts"), payload.get("rec_scores"))
        return {
            "status": "ok",
            "elapsed_seconds": round(time.perf_counter() - start, 3),
            "confidence": mean_confidence(lines),
            "lines": lines,
            "text": "\n".join(line["text"] for line in lines),
        }
    except Exception as error:
        return {
            "status": "error",
            "elapsed_seconds": round(time.perf_counter() - start, 3),
            "error": f"{type(error).__name__}: {error}",
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "images",
        nargs="*",
        type=Path,
        help="Receipt image paths. Defaults to the three images in ocr-benchmark/images/.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"JSON output path (default: {DEFAULT_OUTPUT.relative_to(ROOT)}).",
    )
    args = parser.parse_args()
    paths = [path.resolve() for path in (args.images or DEFAULT_IMAGES)]
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        parser.error("Image file(s) not found: " + ", ".join(missing))

    engines, engine_metadata = load_engines()
    report = {
        "benchmark": "local grocery receipt OCR",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "python_version": sys.version.split()[0],
        "platform": sys.platform,
        "method": "Original image files are passed to each engine. Tesseract uses the project's current preprocessing pipeline. Engine construction time and per-call recognition time are recorded separately. RapidOCR may lazily load models during its first recognition call; PaddleOCR loads models during engine construction.",
        "engines": engine_metadata,
        "images": [],
    }

    for path in paths:
        image_result = {"image": image_metadata(path), "results": {}}
        for engine_name in ("tesseract", "rapidocr", "paddleocr"):
            if engine_name in engines:
                image_result["results"][engine_name] = recognize(
                    engine_name, engines[engine_name], path
                )
            else:
                image_result["results"][engine_name] = {
                    "status": "unavailable",
                    "error": engine_metadata[engine_name].get(
                        "initialization_error", "Engine could not be initialized."
                    ),
                }
        report["images"].append(image_result)

    output_path = args.output.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")

    for image in report["images"]:
        print(f"\n{image['image']['path']} ({image['image']['width']}x{image['image']['height']})")
        for engine_name, result in image["results"].items():
            elapsed = result.get("elapsed_seconds", "—")
            print(f"[{engine_name}] status={result['status']} elapsed_seconds={elapsed}")
            if result.get("text"):
                print(result["text"])
            elif result.get("error"):
                print(result["error"])
    print(f"\nJSON results written to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
