# Набор данных для извлечения из документов

## Выбор схемы

В наборе данных в качестве схемы извлечения по умолчанию используется `default_scheme.json`.

Каждый документ сопоставляется ровно с одной схемой.

| Документ | Схема |
|---|---|
| proforma_invoice_01.pdf | default_scheme.json |
| proforma_invoice_02.pdf | default_scheme.json |
| proforma_invoice_03.pdf | default_scheme.json |
| proforma_invoice_04.pdf | default_scheme.json |
| proforma_invoice_05.pdf | default_scheme.json |
| proforma_invoice_06.pdf | default_scheme.json |
| proforma_invoice_07.pdf | default_scheme.json |
| proforma_invoice_08.pdf | default_scheme.json |
| proforma_invoice_09.pdf | default_scheme.json |
| proforma_invoice_10.pdf | default_scheme.json |

## Правила извлечения

ИИ-агент должен извлекать только поля, определённые выбранной схемой.

Если поле отсутствует в документе:
- скалярное поле → `null`
- поле-массив → `[]`

Агент не должен домысливать отсутствующие значения.

Даты должны использовать формат `ГГГГ-ММ-ДД`.

Валюты должны по возможности использовать коды ISO 4217.

Позиции строк должны сохранять исходный порядок в документе.

## Специальные схемы

Используется один default_scheme.json для всех десяти инвойсов. Специальная схема здесь не нужна: HS code, origin, shipping, packages, weights и Incoterms уже покрываются default-схемой.
