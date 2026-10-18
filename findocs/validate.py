from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal

TOLERANCE = Decimal("0.01")

REQUISITE_LENGTHS = {
    "inn": ((10, 12), "ИНН"),
    "kpp": ((9,), "КПП"),
    "ogrn": ((13, 15), "ОГРН"),
    "bank_account": ((20,), "расчетный счет"),
    "bik": ((9,), "БИК"),
    "corr_account": ((20,), "корр. счет"),
}


@dataclass
class Issue:
    field: str
    code: str
    message: str

    def to_dict(self) -> dict:
        return asdict(self)


def _dec(value) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _differs(a: Decimal, b: Decimal) -> bool:
    return abs(a - b) > TOLERANCE


def _fmt(value: Decimal) -> str:
    return f"{value:,.2f}".replace(",", " ")


def _check_requisites(data: dict) -> list[Issue]:
    issues = []
    for i, party in enumerate(data.get("parties") or []):
        for field, (lengths, label) in REQUISITE_LENGTHS.items():
            value = party.get(field)
            if value is None:
                continue
            if not value.isdigit() or len(value) not in lengths:
                expected = " или ".join(map(str, lengths))
                issues.append(Issue(f"parties[{i}].{field}", "format",
                                    f"{label} {party.get('name')}: ожидается {expected} цифр, получено «{value}»"))
    return issues


def _check_dates(data: dict) -> list[Issue]:
    issues = []

    def parse(field: str, value: str | None) -> date | None:
        if value is None:
            return None
        try:
            return date.fromisoformat(value)
        except ValueError:
            issues.append(Issue(field, "date", f"Несуществующая дата «{value}»"))
            return None

    parse("document_date", data.get("document_date"))
    period = data.get("period") or {}
    start, end = parse("period.from", period.get("from")), parse("period.to", period.get("to"))
    if start and end and start > end:
        issues.append(Issue("period", "date", f"Начало периода {start} позже конца {end}"))
    for i, tx in enumerate(data.get("transactions") or []):
        day = parse(f"transactions[{i}].date", tx.get("date"))
        if day and start and end and not start <= day <= end:
            issues.append(Issue(f"transactions[{i}].date", "date", f"Дата операции {day} вне периода выписки"))
    return issues


def _check_line_items(data: dict) -> list[Issue]:
    issues = []
    items = data.get("line_items") or []
    for i, item in enumerate(items):
        qty, price, amount = _dec(item.get("quantity")), _dec(item.get("unit_price")), _dec(item.get("amount"))
        if None not in (qty, price, amount) and _differs(qty * price, amount):
            issues.append(Issue(f"line_items[{i}].amount", "arithmetic",
                                f"Строка {i + 1}: {qty} × {_fmt(price)} = {_fmt(qty * price)}, а указано {_fmt(amount)}"))

    totals = data.get("totals") or {}
    base, rate = _dec(totals.get("amount_without_vat")), _dec(totals.get("vat_rate"))
    vat, total = _dec(totals.get("vat_amount")), _dec(totals.get("total"))

    amounts = [_dec(item.get("amount")) for item in items]
    if amounts and None not in amounts:
        lines_sum = sum(amounts)
        target, label = (base, "сумма без НДС") if base is not None else (total, "итог")
        if target is not None and _differs(lines_sum, target):
            field = "totals.amount_without_vat" if base is not None else "totals.total"
            issues.append(Issue(field, "arithmetic",
                                f"Сумма строк {_fmt(lines_sum)} не равна полю «{label}» {_fmt(target)}"))

    if None not in (base, rate, vat):
        expected = (base * rate / 100).quantize(TOLERANCE)
        if _differs(expected, vat):
            issues.append(Issue("totals.vat_amount", "arithmetic",
                                f"НДС {rate}% от {_fmt(base)} = {_fmt(expected)}, а указано {_fmt(vat)}"))
    elif base is None and None not in (total, rate, vat):
        expected = (total * rate / (100 + rate)).quantize(TOLERANCE)
        if _differs(expected, vat):
            issues.append(Issue("totals.vat_amount", "arithmetic",
                                f"НДС {rate}% в том числе от {_fmt(total)} = {_fmt(expected)}, а указано {_fmt(vat)}"))
    if None not in (base, vat, total) and _differs(base + vat, total):
        issues.append(Issue("totals.total", "arithmetic",
                            f"{_fmt(base)} + НДС {_fmt(vat)} = {_fmt(base + vat)}, а итог {_fmt(total)}"))
    return issues


def _check_bank_statement(data: dict) -> list[Issue]:
    issues = []
    amounts = [_dec(tx.get("amount")) for tx in data.get("transactions") or []]
    if not amounts or None in amounts:
        return issues
    credit = sum(a for a in amounts if a > 0)
    debit = sum(a for a in amounts if a < 0)
    opening, closing = _dec(data.get("opening_balance")), _dec(data.get("closing_balance"))
    total_credit, total_debit = _dec(data.get("total_credit")), _dec(data.get("total_debit"))

    if total_credit is not None and _differs(credit, abs(total_credit)):
        issues.append(Issue("total_credit", "arithmetic",
                            f"Поступления по операциям {_fmt(credit)}, а в итоге {_fmt(abs(total_credit))}"))
    if total_debit is not None and _differs(abs(debit), abs(total_debit)):
        issues.append(Issue("total_debit", "arithmetic",
                            f"Списания по операциям {_fmt(abs(debit))}, а в итоге {_fmt(abs(total_debit))}"))
    if None not in (opening, total_credit, total_debit, closing):
        expected = opening + abs(total_credit) - abs(total_debit)
        if _differs(expected, closing):
            issues.append(Issue("closing_balance", "arithmetic",
                                f"Остаток {_fmt(opening)} + {_fmt(abs(total_credit))} − {_fmt(abs(total_debit))} = "
                                f"{_fmt(expected)}, а указано {_fmt(closing)}"))
    return issues


def _check_branch_report(data: dict) -> list[Issue]:
    issues = []
    rows = data.get("branch_rows") or []
    money = ("cash", "acquiring", "certificates_other")
    for i, row in enumerate(rows):
        parts = [_dec(row.get(k)) for k in money]
        total = _dec(row.get("total"))
        if None not in parts and total is not None and _differs(sum(parts), total):
            issues.append(Issue(f"branch_rows[{i}].total", "arithmetic",
                                f"{row.get('branch_code')}: сумма колонок {_fmt(sum(parts))}, а итог {_fmt(total)}"))
    totals = data.get("branch_totals") or {}
    for column in ("bookings", "services", *money, "total"):
        values = [_dec(row.get(column)) for row in rows]
        printed = _dec(totals.get(column))
        if rows and None not in values and printed is not None and _differs(sum(values), printed):
            issues.append(Issue(f"branch_totals.{column}", "arithmetic",
                                f"Колонка {column}: сумма строк {sum(values)}, а в итоговой строке {printed}"))
    return issues


def _check_events(data: dict) -> list[Issue]:
    amounts = [_dec(event.get("amount")) for event in data.get("events") or []]
    total = _dec((data.get("totals") or {}).get("total"))
    if amounts and None not in amounts and total is not None and _differs(sum(amounts), total):
        return [Issue("totals.total", "arithmetic", f"Сумма статей сметы {_fmt(sum(amounts))}, а итог {_fmt(total)}")]
    return []


SPECIAL_CHECKS = {
    "bank_statement": _check_bank_statement,
    "branch_report": _check_branch_report,
    "contract_appendix": _check_events,
}


def validate(data: dict) -> list[Issue]:
    issues = _check_requisites(data) + _check_dates(data) + _check_line_items(data)
    special = SPECIAL_CHECKS.get(data.get("document_type"))
    return issues + (special(data) if special else [])
