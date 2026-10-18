import argparse
import difflib
import json
import re
from collections import Counter
from pathlib import Path

from findocs import config

SEMANTIC_FIELDS = {"document_type", "role", "type", "side", "currency", "upd_status", "from", "to"}
FUZZY_FIELDS = {"stamps", "handwritten_notes", "provisions", "subject", "payment_terms", "reporting_terms"}
FUZZY_RATIO = 0.85
UNORDERED_LISTS = {"parties": ("role", "name"), "references": ("type", "number")}
HOMOGLYPHS = str.maketrans("авекмнорстхуё", "abekmhopctxye")
MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября",
          "ноября", "декабря"]


def _norm(value) -> str:
    text = str(value).lower().translate(HOMOGLYPHS)
    return re.sub(r"[\W_]", "", text)


def _same(key, got, fuzzy: bool) -> bool:
    if isinstance(key, (int, float)) and isinstance(got, (int, float)) and not isinstance(key, bool):
        return abs(key - got) < 0.005
    if key is None or got is None:
        return key is got
    a, b = _norm(key), _norm(got)
    return a == b or (fuzzy and difflib.SequenceMatcher(None, a, b).ratio() >= FUZZY_RATIO)


def _text_forms(value) -> list[str]:
    if isinstance(value, bool):
        return []
    if isinstance(value, (int, float)):
        forms = [f"{value:.2f}"]
        if float(value).is_integer():
            forms.append(f"{value:.0f}")
        return [_norm(f) for f in forms]
    text = str(value)
    if match := re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", text):
        year, month, day = match.groups()
        return [_norm(f"{day}.{month}.{year}"), _norm(f"{day}.{month}"),
                _norm(f"{int(day)} {MONTHS[int(month) - 1]} {year}"), _norm(f"{day} {MONTHS[int(month) - 1]} {year}")]
    return [_norm(text)]


def _in_text(value, normalized_text: str) -> bool:
    return any(form and form in normalized_text for form in _text_forms(value))


def _similarity(a: dict, b: dict) -> int:
    score = 0
    for field, value in a.items():
        if value is not None and not isinstance(value, (dict, list)) and _same(value, b.get(field), False):
            score += 2 if field in ("inn", "number", "name") else 1
    return score


def _align(key: dict, got: dict) -> None:
    for name in UNORDERED_LISTS:
        expected, extracted = key.get(name), got.get(name)
        if not isinstance(expected, list) or not isinstance(extracted, list):
            continue
        pool = [i for i in extracted if isinstance(i, dict)]
        ordered = []
        for item in expected:
            best = max(pool, key=lambda candidate: _similarity(item, candidate), default=None)
            if best is not None and _similarity(item, best) > 0:
                pool.remove(best)
                ordered.append(best)
            else:
                ordered.append({})
        got[name] = ordered + pool


def _leaves(key, got, path: str, top: str):
    if isinstance(key, dict):
        got = got if isinstance(got, dict) else {}
        for name, value in key.items():
            yield from _leaves(value, got.get(name), f"{path}.{name}" if path else name, top or name)
    elif isinstance(key, list):
        got = got if isinstance(got, list) else []
        for i, value in enumerate(key):
            yield from _leaves(value, got[i] if i < len(got) else None, f"{path}[{i}]", top)
        for i in range(len(key), len(got)):
            if got[i] is not None:
                yield f"{path}[{i}]", top, None, got[i]
    else:
        yield path, top, key, got


def classify(key, got, field: str, top: str, text: str) -> str:
    fuzzy = top in FUZZY_FIELDS
    if _same(key, got, fuzzy):
        return "correct"
    semantic = field in SEMANTIC_FIELDS or isinstance(got, (bool, dict, list)) or isinstance(key, bool)
    if got is not None and (key is None or (not semantic and not _in_text(got, text))):
        return "hallucinated"
    if semantic or _in_text(key, text):
        return "struct_error"
    return "ocr_error"


def evaluate(keys_dir: Path, manual_seconds: float) -> dict:
    documents, totals = [], Counter()
    for key_file in sorted(keys_dir.glob("*_p*.json")):
        key = json.loads(key_file.read_text(encoding="utf-8"))
        page_dir = config.RESULTS_DIR / Path(key["source_file"]).stem
        result_file = page_dir / f"p{key['page']}.json"
        if not result_file.exists():
            continue
        result = json.loads(result_file.read_text(encoding="utf-8"))
        text = _norm((page_dir / f"p{key['page']}.ocr.txt").read_text(encoding="utf-8"))
        expected, got = key["expected"], result["data"] or {}
        _align(expected, got)

        counts, errors = Counter(), []
        for path, top, key_value, got_value in _leaves(expected, got, "", ""):
            field = re.sub(r"\[\d+\]", "", path).split(".")[-1]
            verdict = classify(key_value, got_value, field, top, text)
            counts[verdict] += 1
            if verdict != "correct":
                errors.append({"field": path, "verdict": verdict, "key": key_value, "got": got_value})
        stats = result["stats"]
        seconds = stats["ocr_seconds"] + stats["extract_seconds"] + stats["agent_seconds"]
        tokens = stats["ocr_tokens"] + stats["extract_tokens"] + stats["agent_tokens"]
        documents.append({"document": key_file.stem, "status": result["status"], "fields": sum(counts.values()),
                          **counts, "seconds": round(seconds, 1), "tokens": tokens, "errors": errors})
        totals.update(counts)
        totals.update(seconds=seconds, tokens=tokens, approved=result["status"] == "approved")

    count = len(documents)
    fields = sum(totals[v] for v in ("correct", "hallucinated", "ocr_error", "struct_error"))
    stp_rate = totals["approved"] / count if count else 0.0
    avg_seconds = totals["seconds"] / count if count else 0.0
    summary = {
        "documents": count,
        "fields": fields,
        "accuracy": totals["correct"] / fields if fields else 0.0,
        "ocr_error_rate": totals["ocr_error"] / fields if fields else 0.0,
        "struct_error_rate": totals["struct_error"] / fields if fields else 0.0,
        "hallucination_rate": totals["hallucinated"] / fields if fields else 0.0,
        "stp_rate": stp_rate,
        "avg_seconds_per_document": avg_seconds,
        "manual_seconds_per_document": manual_seconds,
        "operator_seconds_saved_per_document": stp_rate * manual_seconds,
        "tokens": totals["tokens"],
    }
    return {"summary": summary, "documents": documents}


def main() -> None:
    parser = argparse.ArgumentParser(prog="findocs.evaluate", description="Compare pipeline results with keys.")
    parser.add_argument("--keys", type=Path, default=config.ROOT / "corporative_docs" / "keys")
    parser.add_argument("--manual-seconds", type=float, default=config.MANUAL_SECONDS_PER_DOCUMENT,
                        help="assumed time an operator spends on one document by hand")
    parser.add_argument("-v", "--verbose", action="store_true", help="print every mismatched field")
    args = parser.parse_args()

    report = evaluate(args.keys, args.manual_seconds)
    (config.RESULTS_DIR / "metrics.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")

    print(f"{'document':28} {'status':13} {'fields':>6} {'ok':>5} {'ocr':>4} {'llm':>4} {'hall':>4} {'sec':>6}")
    for d in report["documents"]:
        print(f"{d['document']:28} {d['status']:13} {d['fields']:6} {d.get('correct', 0):5} {d.get('ocr_error', 0):4} "
              f"{d.get('struct_error', 0):4} {d.get('hallucinated', 0):4} {d['seconds']:6}")
        if args.verbose:
            for e in d["errors"]:
                print(f"    [{e['verdict']}] {e['field']}: key={e['key']!r} got={e['got']!r}")
    s = report["summary"]
    print(f"\nAccuracy {s['accuracy']:.1%} | OCR errors {s['ocr_error_rate']:.1%} | "
          f"structuring errors {s['struct_error_rate']:.1%} | hallucinations {s['hallucination_rate']:.1%}")
    print(f"STP rate {s['stp_rate']:.0%} | {s['avg_seconds_per_document']:.0f} s per document | "
          f"operator time saved ≈ {s['operator_seconds_saved_per_document'] / 60:.1f} min per document "
          f"(assuming {s['manual_seconds_per_document'] / 60:.0f} min by hand) | {s['tokens']} tokens")


if __name__ == "__main__":
    main()
