import difflib
import re
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from findocs import config

LEGAL_FORMS = r"\b(ооо|ао|пао|зао|ип|общество с ограниченной ответственностью|акционерное общество)\b"
COMPARED_FIELDS = ("inn", "kpp", "address", "phone", "email", "bank_account")


@contextmanager
def connect():
    with psycopg.connect(config.DATABASE_URL, row_factory=dict_row) as connection:
        yield connection


def _name_key(name: str) -> str:
    name = re.sub(r"[«»\"“”„']", " ", name.lower())
    return re.sub(r"\s+", " ", re.sub(LEGAL_FORMS, " ", name)).strip()


def _name_score(a: str, b: str) -> float:
    a, b = _name_key(a), _name_key(b)
    if not a or not b:
        return 0.0
    if a in b or b in a:
        return 1.0
    tokens_a, tokens_b = set(a.split()), set(b.split())
    jaccard = len(tokens_a & tokens_b) / len(tokens_a | tokens_b)
    return max(jaccard, difflib.SequenceMatcher(None, a, b).ratio())


def _same(field: str, a: str, b: str) -> bool:
    if field in ("inn", "kpp", "phone", "bank_account"):
        return re.sub(r"\D", "", a) == re.sub(r"\D", "", b)
    a, b = re.sub(r"[\W_]", "", a.lower()), re.sub(r"[\W_]", "", b.lower())
    if field == "address":
        return a in b or b in a
    return a == b


def _edit_distance(a: str, b: str) -> int:
    previous = list(range(len(b) + 1))
    for i, char_a in enumerate(a, 1):
        current = [i]
        for j, char_b in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (char_a != char_b)))
        previous = current
    return previous[-1]


def _difference(field: str, document: str, registry: str) -> dict:
    difference = {"field": field, "document": document, "registry": registry}
    if field in ("inn", "kpp", "bank_account") and _edit_distance(document, registry) <= 2:
        difference["note"] = "отличается на 1–2 символа: вероятна ошибка распознавания"
    return difference


def _branch_code(name: str) -> str | None:
    match = re.search(r"\b([CС][HН])-(\d{2})\b", name.upper())
    return f"CH-{match.group(2)}" if match else None


def _lookup_branch(code: str, address: str | None) -> dict:
    with connect() as connection:
        branch = connection.execute("SELECT * FROM branches WHERE code = %s", (code,)).fetchone()
    if branch is None:
        return {"status": "not_found", "message": f"Подразделения {code} нет в справочнике"}
    differences = ([{"field": "address", "document": address, "registry": branch["address"]}]
                   if address and not _same("address", address, branch["address"]) else [])
    return {"status": "found_different_requisites" if differences else "found",
            "registry": {"branch": code, "name": branch["name"], "address": branch["address"]},
            "differences": differences}


def lookup_supplier(name: str, inn: str | None = None, kpp: str | None = None, address: str | None = None,
                    phone: str | None = None, email: str | None = None, bank_account: str | None = None) -> dict:
    if not inn and (code := _branch_code(name)):
        return _lookup_branch(code, address)
    given = {"inn": inn, "kpp": kpp, "address": address, "phone": phone, "email": email, "bank_account": bank_account}
    with connect() as connection:
        rows = connection.execute("SELECT * FROM counterparties").fetchall()

    record = next((row for row in rows if inn and row["inn"] and _same("inn", row["inn"], inn)), None)
    if record is None:
        scored = sorted(((_name_score(name, row["name"]), row) for row in rows), key=lambda x: x[0], reverse=True)
        if scored and scored[0][0] >= 0.5:
            record = scored[0][1]
    if record is None:
        return {"status": "not_found", "message": f"«{name}» нет в справочнике контрагентов"}

    differences = [
        _difference(field, value, record[field])
        for field, value in given.items()
        if value and record[field] and not _same(field, value, record[field])
    ]
    if _name_score(name, record["name"]) < 0.5:
        differences.insert(0, {"field": "name", "document": name, "registry": record["name"]})
    return {
        "status": "found_different_requisites" if differences else "found",
        "registry": {k: record[k] for k in ("name", *COMPARED_FIELDS, "is_own_company")},
        "differences": differences,
    }


def list_documents() -> list[dict]:
    with connect() as connection:
        return connection.execute(
            "SELECT id, source_file, page, document_type, status, reason, review_fields, issues, processed_at "
            "FROM documents ORDER BY source_file, page"
        ).fetchall()


def get_document(document_id: int) -> dict | None:
    with connect() as connection:
        return connection.execute("SELECT * FROM documents WHERE id = %s", (document_id,)).fetchone()


def list_counterparties() -> list[dict]:
    with connect() as connection:
        return connection.execute("SELECT * FROM counterparties ORDER BY is_own_company DESC, name").fetchall()


def save_document(source_file: str, page: int, document_type: str, status: str, reason: str | None,
                  review_fields: list[str], issues: list[dict], data: dict | None) -> None:
    with connect() as connection:
        connection.execute(
            """
            INSERT INTO documents (source_file, page, document_type, status, reason, review_fields, issues, data)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (source_file, page) DO UPDATE SET
                document_type = EXCLUDED.document_type, status = EXCLUDED.status, reason = EXCLUDED.reason,
                review_fields = EXCLUDED.review_fields, issues = EXCLUDED.issues, data = EXCLUDED.data,
                processed_at = now()
            """,
            (source_file, page, document_type, status, reason, Jsonb(review_fields), Jsonb(issues), Jsonb(data)),
        )
