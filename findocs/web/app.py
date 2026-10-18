import io
import json
import threading
import uuid
from functools import lru_cache
from pathlib import Path

import pypdfium2 as pdfium
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from findocs import config, db, evaluate, pdf
from findocs.pipeline import process_pdf

STATIC_DIR = Path(__file__).parent / "static"
SAMPLES_DIR = config.ROOT / "corporative_docs" / "scans"
KEYS_DIR = config.ROOT / "corporative_docs" / "keys"
MAX_UPLOAD_BYTES = 25 * 1024 * 1024

app = FastAPI(title="Я, Ревизор")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/icons", StaticFiles(directory=config.ICONS_DIR), name="icons")

_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


def _update_job(job_id: str, **fields) -> None:
    with _jobs_lock:
        _jobs[job_id].update(fields)


def _run_job(job_id: str, path: Path, fresh_ocr: bool) -> None:
    def progress(stage: str, page: int, pages: int) -> None:
        _update_job(job_id, stage=stage, page=page, pages=pages)

    try:
        results = process_pdf(path, fresh_ocr=fresh_ocr, progress=progress)
        _update_job(job_id, state="done", stage="done", results=[
            {"page": r.page, "document_type": r.document_type, "status": r.status, "reason": r.reason}
            for r in results
        ])
    except Exception as error:
        _update_job(job_id, state="error", stage="error", error=f"{type(error).__name__}: {error}")


def _start_job(path: Path, fresh_ocr: bool) -> dict:
    job_id = uuid.uuid4().hex
    with _jobs_lock:
        _jobs[job_id] = {"id": job_id, "file": path.name, "state": "running", "stage": "render",
                         "page": 0, "pages": 0, "results": [], "error": None}
    threading.Thread(target=_run_job, args=(job_id, path, fresh_ocr), daemon=True).start()
    return {"job_id": job_id}


def _source_path(file_name: str) -> Path | None:
    for folder in (config.UPLOADS_DIR, SAMPLES_DIR):
        candidate = folder / Path(file_name).name
        if candidate.exists():
            return candidate
    return None


@lru_cache(maxsize=32)
def _page_png(path: Path, page: int, mtime: float) -> bytes:
    image = pdf.render_pages(path)[page - 1]
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/status")
def status() -> dict:
    try:
        db.list_counterparties()
        database = True
    except Exception:
        database = False
    return {"model": config.DEEPSEEK_MODEL, "database": database}


@app.get("/api/samples")
def samples() -> list[dict]:
    result = []
    for path in sorted(SAMPLES_DIR.glob("*.pdf")):
        document = pdfium.PdfDocument(path)
        result.append({"name": path.name, "pages": len(document)})
        document.close()
    return result


@app.post("/api/samples/{name}/process")
def process_sample(name: str, fresh_ocr: bool = False) -> dict:
    path = SAMPLES_DIR / Path(name).name
    if not path.exists():
        raise HTTPException(404, "Нет такого образца")
    return _start_job(path, fresh_ocr)


@app.post("/api/upload")
async def upload(file: UploadFile, fresh_ocr: bool = True) -> dict:
    name = Path(file.filename or "").name
    if not name.lower().endswith(".pdf"):
        raise HTTPException(400, "Нужен файл PDF")
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Файл больше 25 МБ")
    if not content.startswith(b"%PDF"):
        raise HTTPException(400, "Файл не похож на PDF")
    config.UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    path = config.UPLOADS_DIR / name
    path.write_bytes(content)
    return _start_job(path, fresh_ocr)


@app.get("/api/jobs/{job_id}")
def job(job_id: str) -> dict:
    with _jobs_lock:
        if job_id not in _jobs:
            raise HTTPException(404, "Нет такой задачи")
        return dict(_jobs[job_id])


@app.get("/api/documents")
def documents() -> list[dict]:
    return db.list_documents()


@app.get("/api/documents/{document_id}")
def document(document_id: int) -> dict:
    row = db.get_document(document_id)
    if row is None:
        raise HTTPException(404, "Нет такого документа")
    page_dir = config.RESULTS_DIR / Path(row["source_file"]).stem
    result_file, ocr_file = page_dir / f"p{row['page']}.json", page_dir / f"p{row['page']}.ocr.txt"
    result = json.loads(result_file.read_text(encoding="utf-8")) if result_file.exists() else {}
    return {
        **row,
        "ocr_text": ocr_file.read_text(encoding="utf-8") if ocr_file.exists() else None,
        "agent_trace": result.get("agent_trace", []),
        "corrections": result.get("corrections", {}),
        "stats": result.get("stats", {}),
        "has_image": _source_path(row["source_file"]) is not None,
    }


@app.get("/api/documents/{document_id}/image")
def document_image(document_id: int) -> Response:
    row = db.get_document(document_id)
    path = _source_path(row["source_file"]) if row else None
    if path is None:
        raise HTTPException(404, "Скан не найден")
    return Response(_page_png(path, row["page"], path.stat().st_mtime), media_type="image/png")


@app.get("/api/queue")
def queue() -> list[dict]:
    with db.connect() as connection:
        return connection.execute("SELECT * FROM review_queue").fetchall()


@app.get("/api/counterparties")
def counterparties() -> list[dict]:
    return db.list_counterparties()


@app.get("/api/metrics")
def metrics() -> dict:
    path = config.RESULTS_DIR / "metrics.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


@app.post("/api/metrics")
def recompute_metrics() -> dict:
    report = evaluate.evaluate(KEYS_DIR, config.MANUAL_SECONDS_PER_DOCUMENT)
    config.RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (config.RESULTS_DIR / "metrics.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    return report
