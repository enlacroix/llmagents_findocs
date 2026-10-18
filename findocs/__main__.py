import argparse
from pathlib import Path

from findocs.pipeline import process_pdf


def main() -> None:
    parser = argparse.ArgumentParser(prog="findocs", description="Extract structured data from scanned documents.")
    parser.add_argument("paths", nargs="+", type=Path, help="PDF files or folders with PDF files")
    parser.add_argument("--pages", nargs="+", type=int, help="process only these pages (1-based)")
    parser.add_argument("--fresh-ocr", action="store_true", help="run OCR again even if its text is saved")
    args = parser.parse_args()

    pdfs = [p for path in args.paths for p in (sorted(path.glob("*.pdf")) if path.is_dir() else [path])]
    for pdf_path in pdfs:
        for page in process_pdf(pdf_path, pages=args.pages, fresh_ocr=args.fresh_ocr):
            print(f"{pdf_path.name} p{page.page}: {page.document_type} — {page.status} -> {page.output}")
            print(f"    {page.reason}")


if __name__ == "__main__":
    main()
