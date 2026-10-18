from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image

from findocs import config


def render_pages(pdf_path: Path, width: int = config.OCR_IMAGE_WIDTH) -> list[Image.Image]:
    document = pdfium.PdfDocument(pdf_path)
    try:
        images = []
        for page in document:
            scale = width / page.get_width()
            images.append(page.render(scale=scale).to_pil().convert("RGB"))
        return images
    finally:
        document.close()
