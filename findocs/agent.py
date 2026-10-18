import copy
import json
import re
from dataclasses import dataclass, field

from findocs import db, llm, schemes
from findocs.validate import validate as check

MAX_STEPS = 6
CRITICAL_FIELDS = {"inn", "kpp", "bank_account"}

SYSTEM_PROMPT = """Ты проверяешь документ, данные которого уже извлечены из скана (OCR + LLM).
Реши: одобрить его автоматически или отправить человеку на пересмотр.

Порядок работы:
1. Вызови validate() и lookup_supplier для каждой стороны из parties — всё в одном шаге.
2. Если validate не нашел проблем и все стороны найдены без расхождений — сразу вызови approve.
   Перепроверять значения без повода не нужно.
3. Если проблемы есть, проверь через search_text только спорные значения.
   - Поле заполнено, но в тексте нет ни значения, ни подписи этого поля (например, «без НДС») — это ошибка
     извлечения: исправь через validate(corrections), обычно на null.
   - Значение так и напечатано в тексте — не исправляй: противоречие в самом документе или расхождение
     со справочником — повод отправить человеку.
   - Текст получен OCR и сам может содержать ошибки. Если реквизит отличается от справочника на 1–2 символа,
     укажи в причине, что вероятна ошибка распознавания.
   Исправлять через validate(corrections) можно один раз и только поля из проблем, найденных validate.
4. Заверши работу вызовом approve или send_for_revision. Причину пиши по-русски, коротко и конкретно:
   какие поля, что не так и почему это важно."""

MAX_SEARCHES = 6
FINAL_TOOLS = {"approve", "send_for_revision"}

TOOLS = [
    {"type": "function", "function": {
        "name": "validate",
        "description": "Проверка кодом: схема, форматы реквизитов, даты, арифметика. Без аргументов проверяет текущие "
                       "данные. corrections — один раз за документ: исправления вида {\"parties[0].kpp\": \"590001001\"}.",
        "parameters": {"type": "object", "properties": {
            "corrections": {"type": "object", "description": "Путь к полю -> новое значение (null допустим)."}}},
    }},
    {"type": "function", "function": {
        "name": "search_text",
        "description": "Ищет значение в тексте OCR без учета пробелов, регистра и знаков. Возвращает найденные строки.",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
    }},
    {"type": "function", "function": {
        "name": "lookup_supplier",
        "description": "Сверяет сторону документа со справочником контрагентов и подразделений: "
                       "found / found_different_requisites (с перечнем расхождений) / not_found.",
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string"}, "inn": {"type": "string"}, "kpp": {"type": "string"},
            "address": {"type": "string"}, "phone": {"type": "string"}, "email": {"type": "string"},
            "bank_account": {"type": "string"}},
            "required": ["name"]},
    }},
    {"type": "function", "function": {
        "name": "approve",
        "description": "Одобрить документ. Код откажет, если проверки не пройдены или ИНН/КПП/счет стороны "
                       "расходятся со справочником.",
        "parameters": {"type": "object", "properties": {"comment": {"type": "string"}}},
    }},
    {"type": "function", "function": {
        "name": "send_for_revision",
        "description": "Отправить документ человеку на пересмотр.",
        "parameters": {"type": "object", "properties": {
            "reason": {"type": "string", "description": "Причина для оператора."},
            "fields": {"type": "array", "items": {"type": "string"}, "description": "Пути спорных полей."}},
            "required": ["reason", "fields"]},
    }},
]


@dataclass
class Decision:
    status: str
    reason: str
    fields: list[str]
    data: dict
    issues: list[dict]
    corrections: dict = field(default_factory=dict)
    trace: list[dict] = field(default_factory=list)
    calls: list[llm.LLMResult] = field(default_factory=list)


def _normalize(text: str) -> str:
    return re.sub(r"[\W_]", "", text.lower())


def _set_path(data: dict, path: str, value) -> None:
    keys = [int(k[1:-1]) if k.startswith("[") else k for k in re.findall(r"\[\d+\]|[^.\[\]]+", path)]
    target = data
    for key in keys[:-1]:
        target = target[key]
    if isinstance(keys[-1], str) and keys[-1] not in target:
        raise KeyError(path)
    target[keys[-1]] = value


class Review:
    def __init__(self, text: str, data: dict, scheme: str):
        self.text, self.data, self.scheme = text, data, scheme
        self.corrections: dict = {}
        self.searches = 0
        self.decision: tuple[str, str, list[str]] | None = None

    def issues(self, data: dict | None = None) -> list[dict]:
        data = self.data if data is None else data
        schema_errors = [{"field": e.split(":")[0], "code": "schema", "message": e}
                         for e in schemes.validate(data, self.scheme)]
        return schema_errors + [issue.to_dict() for issue in check(data)]

    def validate(self, corrections: dict | None = None) -> dict:
        if not corrections:
            return {"issues": self.issues()}
        if self.corrections:
            return {"error": "Исправление уже использовано", "issues": self.issues()}
        unverified = [path for path, value in corrections.items() if value is not None and not self._in_text(value)]
        if unverified:
            return {"error": "Новых значений нет в тексте OCR: исправлять можно только на то, что напечатано "
                             "в документе. Расхождение со справочником — повод для send_for_revision.",
                    "fields": unverified, "issues": self.issues()}
        candidate = copy.deepcopy(self.data)
        try:
            for path, value in corrections.items():
                _set_path(candidate, path, value)
        except (KeyError, IndexError, TypeError) as error:
            return {"error": f"Нет такого поля: {error}", "issues": self.issues()}
        if schema_errors := schemes.validate(candidate, self.scheme):
            return {"error": "Исправления нарушают схему", "schema_errors": schema_errors[:10]}
        self.data, self.corrections = candidate, corrections
        return {"applied": corrections, "issues": self.issues()}

    def _matching_lines(self, value) -> list[str]:
        query = str(value)
        needles = {_normalize(query)}
        try:
            number = float(query.replace(" ", "").replace(",", "."))
            needles |= {_normalize(f"{number:.2f}"), _normalize(f"{number:.0f}") if number.is_integer() else ""}
        except ValueError:
            pass
        needles.discard("")
        return [f"{n}: {line.strip()}" for n, line in enumerate(self.text.splitlines(), 1)
                if any(needle in _normalize(line) for needle in needles)]

    def _in_text(self, value) -> bool:
        return isinstance(value, bool) or bool(self._matching_lines(value))

    def search_text(self, query: str) -> dict:
        self.searches += 1
        if self.searches > MAX_SEARCHES:
            return {"error": "Лимит поиска исчерпан: прими решение — approve или send_for_revision"}
        lines = self._matching_lines(query)
        return {"found": bool(lines), "lines": lines[:8]}

    def critical_differences(self) -> list[str]:
        found = []
        for i, party in enumerate(self.data.get("parties") or []):
            if not party.get("name"):
                continue
            result = db.lookup_supplier(party["name"], party.get("inn"), party.get("kpp"),
                                        bank_account=party.get("bank_account"))
            found += [f"parties[{i}].{d['field']}" for d in result.get("differences", []) if d["field"] in CRITICAL_FIELDS]
        return found

    def approve(self, comment: str = "") -> dict:
        if issues := self.issues():
            return {"refused": "Нельзя одобрить: проверки не пройдены", "issues": issues}
        if differences := self.critical_differences():
            return {"refused": "Нельзя одобрить: реквизиты расходятся со справочником", "fields": differences}
        self.decision = ("approved", comment or "Проверки пройдены", [])
        return {"ok": True}

    def send_for_revision(self, reason: str, fields: list[str]) -> dict:
        self.decision = ("needs_review", reason, fields)
        return {"ok": True}

    def run_tool(self, name: str, arguments: dict) -> dict:
        if name == "lookup_supplier":
            return db.lookup_supplier(**{k: v for k, v in arguments.items() if v})
        return getattr(self, name)(**arguments)


def review(text: str, data: dict, scheme: str) -> Decision:
    session = Review(text, copy.deepcopy(data), scheme)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "Извлеченные данные:\n" + json.dumps(data, ensure_ascii=False)},
    ]
    trace, calls = [], []

    for step in range(1, MAX_STEPS + 1):
        tools = TOOLS if step < MAX_STEPS else [t for t in TOOLS if t["function"]["name"] in FINAL_TOOLS]
        result = llm.chat(messages, tools=tools)
        calls.append(result)
        messages.append(result.as_message())
        if not result.tool_calls:
            messages.append({"role": "user", "content": "Заверши работу: вызови approve или send_for_revision."})
            continue
        for call in result.tool_calls:
            try:
                arguments = json.loads(call.arguments or "{}")
                output = session.run_tool(call.name, arguments)
            except Exception as error:
                arguments, output = call.arguments, {"error": f"{type(error).__name__}: {error}"}
            trace.append({"tool": call.name, "arguments": arguments, "result": output})
            messages.append({"role": "tool", "tool_call_id": call.id,
                             "content": json.dumps(output, ensure_ascii=False, default=str)})
        if session.decision:
            break

    status, reason, fields = session.decision or (
        "needs_review", f"Агент не принял решение за {MAX_STEPS} шагов", [i["field"] for i in session.issues()])
    return Decision(status, reason, fields, session.data, session.issues(), session.corrections, trace, calls)
