## Schema selection

The dataset uses `default_scheme.json` as the default extraction schema.

Each document is mapped to exactly one schema.

| Document | Schema |
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

## Extraction rules

The AI agent must extract only fields defined by the selected schema.

If a field is not present in the document:
- scalar field → `null`
- array field → `[]`

The agent must not infer missing values.

Dates should use `YYYY-MM-DD`.

Currencies should use ISO 4217 codes where possible.

Line items must preserve their original document order.

## Special schemas

A single default_scheme.json is used for all ten invoices. No special schema is needed here: HS code, origin, shipping, packages, weights, and Incoterms are already covered by the default schema.
