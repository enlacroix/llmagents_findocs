import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from findocs import agent, config, db, extract, ocr, pdf


@dataclass
class PageResult:
    page: int
    document_type: str
    status: str
    reason: str
    output: Path


def _tokens(calls) -> int:
    return sum(c.prompt_tokens + c.completion_tokens for c in calls)


Progress = Callable[[str, int, int], None]


def process_pdf(pdf_path: Path, pages: list[int] | None = None, fresh_ocr: bool = False,
                progress: Progress | None = None) -> list[PageResult]:
    out_dir = config.RESULTS_DIR / pdf_path.stem
    out_dir.mkdir(parents=True, exist_ok=True)
    images = pdf.render_pages(pdf_path)
    selected = [n for n in range(1, len(images) + 1) if not pages or n in pages]
    report = progress or (lambda stage, page, total: None)
    results = []

    for number in selected:
        image = images[number - 1]
        ocr_file = out_dir / f"p{number}.ocr.txt"
        ocr_calls = []
        report("ocr", number, len(selected))
        if ocr_file.exists() and not fresh_ocr:
            text = ocr_file.read_text(encoding="utf-8")
        else:
            ocr_calls.append(ocr.ocr_page(image))
            text = ocr_calls[0].text
            ocr_file.write_text(text, encoding="utf-8")

        report("extract", number, len(selected))
        extraction = extract.extract(text)
        report("agent", number, len(selected))
        if extraction.errors:
            decision = agent.Decision("needs_review", "Извлеченные данные не прошли проверку схемы",
                                      [e.split(":")[0] for e in extraction.errors], extraction.data or {},
                                      [{"field": e.split(":")[0], "code": "schema", "message": e}
                                       for e in extraction.errors])
        else:
            decision = agent.review(text, extraction.data, extraction.scheme)

        output = out_dir / f"p{number}.json"
        output.write_text(json.dumps({
            "source_file": pdf_path.name,
            "page": number,
            "document_type": extraction.document_type,
            "schema": extraction.scheme,
            "status": decision.status,
            "reason": decision.reason,
            "review_fields": decision.fields,
            "issues": decision.issues,
            "corrections": decision.corrections,
            "stats": {
                "ocr_seconds": round(sum(c.seconds for c in ocr_calls), 2),
                "extract_seconds": round(sum(c.seconds for c in extraction.calls), 2),
                "agent_seconds": round(sum(c.seconds for c in decision.calls), 2),
                "ocr_tokens": _tokens(ocr_calls),
                "extract_tokens": _tokens(extraction.calls),
                "agent_tokens": _tokens(decision.calls),
                "extract_attempts": extraction.attempts,
                "agent_steps": len(decision.calls),
            },
            "agent_trace": decision.trace,
            "extracted": extraction.data,
            "data": decision.data,
        }, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")

        db.save_document(pdf_path.name, number, extraction.document_type, decision.status, decision.reason,
                         decision.fields, decision.issues, decision.data)
        results.append(PageResult(number, extraction.document_type, decision.status, decision.reason, output))
    return results
