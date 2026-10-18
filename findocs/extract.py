import json
from dataclasses import dataclass, field

from findocs import llm, schemes

CLASSIFY_PROMPT = """Определи тип документа по его тексту. Верни JSON вида {{"document_type": "<тип>"}}.
Допустимые типы: {types}.
company_card — карточка предприятия; order — приказ; bank_statement — банковская выписка;
branch_report — сводный отчет по филиалам; invoice — счет на оплату; transfer_document — УПД или накладная;
service_act — акт оказанных услуг; placement_registry — реестр к акту; contract — договор;
contract_appendix — приложение к договору (план, смета); participants_list — список участников мероприятий;
tax_invoice — счет-фактура; payment_order — платежное поручение; reconciliation_act — акт сверки расчетов;
transport_order — договор-заявка на перевозку; vehicle_transfer_act — акт приема-передачи транспортного средства;
insurance_policy — страховой полис; power_of_attorney — доверенность; waybill — путевой лист."""

EXTRACT_PROMPT = """Ты извлекаешь данные из текста документа, полученного OCR со скана.
Верни один JSON-объект, валидный по схеме ниже. document_type = "{document_type}".

Правила:
- В ответе должны быть все поля схемы. Нет значения в тексте: скалярное поле — null, список — [].
- Ничего не домысливай: только то, что есть в тексте. Значения бери как напечатаны, даже если они кажутся ошибочными.
- Ничего не вычисляй. Если в документе нет цены за единицу или суммы без НДС, эти поля — null, даже если их можно
  посчитать. «Итого ... в т.ч. НДС» — это total и vat_amount, а amount_without_vat остается null.
- Даты — YYYY-MM-DD. Год для дат вида «15.09» бери из периода документа.
- Суммы — числа с точкой, без пробелов; знак сохраняй, если он напечатан. Ставка НДС — в процентах (22).
- ИНН, КПП, ОГРН, счета, БИК — строки из цифр без пробелов. Если число цифр кажется неправильным, всё равно перепиши
  как прочитано: формат проверит код.
- Названия организаций — коротко, с кавычками-ёлочками: ООО «Ромашка». ФИО представителя — в именительном падеже.
- Реквизиты стороны можно брать и с её печати.
- Строки таблиц — в исходном порядке.
- Строки OCR с префиксами [печать] и [рукопись] — это печати и рукописные пометки, по одной на строку.
- Фрагменты [?] и [неразборчиво] не являются значениями: не переноси их в поля.

Схема:
{schema}"""

FIX_PROMPT = """Ответ не прошел проверку по схеме. Ошибки:
{errors}
Исправь их и верни полный JSON-объект заново."""


@dataclass
class Extraction:
    document_type: str
    scheme: str
    data: dict | None
    errors: list[str]
    attempts: int
    calls: list[llm.LLMResult] = field(default_factory=list)


def classify(text: str) -> tuple[str, llm.LLMResult]:
    types = schemes.document_types()
    result = llm.chat([
        {"role": "system", "content": CLASSIFY_PROMPT.format(types=", ".join(types))},
        {"role": "user", "content": text},
    ], json_mode=True)
    document_type = json.loads(result.text).get("document_type")
    if document_type not in types:
        raise ValueError(f"Unknown document type from LLM: {document_type!r}")
    return document_type, result


def _parse(text: str) -> tuple[dict | None, list[str]]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        return None, [f"<root>: invalid JSON: {error}"]
    if not isinstance(data, dict):
        return None, ["<root>: expected a JSON object"]
    return data, []


def extract(text: str, max_attempts: int = 2) -> Extraction:
    document_type, classify_call = classify(text)
    scheme = schemes.scheme_for(document_type)
    messages = [
        {"role": "system", "content": EXTRACT_PROMPT.format(document_type=document_type,
                                                            schema=schemes.prompt_text(scheme))},
        {"role": "user", "content": text},
    ]
    extraction = Extraction(document_type, scheme, None, [], 0, [classify_call])

    while extraction.attempts < max_attempts:
        result = llm.chat(messages, json_mode=True)
        extraction.calls.append(result)
        extraction.attempts += 1
        data, errors = _parse(result.text)
        if data is not None:
            errors = schemes.validate(data, scheme)
        extraction.data, extraction.errors = data, errors
        if not errors:
            break
        messages += [
            {"role": "assistant", "content": result.text},
            {"role": "user", "content": FIX_PROMPT.format(errors="\n".join(errors[:30]))},
        ]
    return extraction
