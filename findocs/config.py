import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-flash")

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://findocs:findocs@localhost:5432/findocs")

SCHEMES_DIR = Path(os.environ.get("SCHEMES_DIR", ROOT / "corporative_docs" / "schemes"))
RESULTS_DIR = Path(os.environ.get("RESULTS_DIR", ROOT / "results"))
UPLOADS_DIR = Path(os.environ.get("UPLOADS_DIR", ROOT / "uploads"))
ICONS_DIR = Path(os.environ.get("ICONS_DIR", ROOT / "icons"))

MANUAL_SECONDS_PER_DOCUMENT = float(os.environ.get("MANUAL_SECONDS_PER_DOCUMENT", "300"))

OCR_IMAGE_WIDTH = int(os.environ.get("OCR_IMAGE_WIDTH", "1200"))
