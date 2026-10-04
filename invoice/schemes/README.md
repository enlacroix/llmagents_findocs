## Schema selection

The invoice dataset uses `default_scheme.json` as the default extraction schema.

Each document is mapped to exactly one schema.

| Document | Key file | Schema |
|---|---|---|
| 01_uae_dense_vat.pdf | keys/01_uae_dense_vat.json | schemes/default_scheme.json |
| 02_saudi_discounted_wholesale.pdf | keys/02_saudi_discounted_wholesale.json | schemes/default_scheme.json |
| 03_kuwait_three_decimal.pdf | keys/03_kuwait_three_decimal.json | schemes/default_scheme.json |
| 04_malaysia_import_landed_cost.pdf | keys/04_malaysia_import_landed_cost.json | schemes/default_scheme.json |
| 05_multi_page_lot_batch.pdf | keys/05_multi_page_lot_batch.json | schemes/default_scheme.json |
| 06_case_pack_conversion.pdf | keys/06_case_pack_conversion.json | schemes/default_scheme.json |
| 07_bonus_quantity_foc.pdf | keys/07_bonus_quantity_foc.json | schemes/default_scheme.json |
| 08_mixed_tax_and_discounts.pdf | keys/08_mixed_tax_and_discounts.json | schemes/default_scheme.json |
| 09_landscape_multicolumn.pdf | keys/09_landscape_multicolumn.json | schemes/default_scheme.json |
| 10_rebate_fees_split_shipment.pdf | keys/10_rebate_fees_split_shipment.json | schemes/default_scheme.json |

## Extraction rules

The AI agent must extract only fields defined by the selected schema.

If a field is not present in the document:
- scalar field -> `null`
- array field -> `[]`

Dates should use `YYYY-MM-DD`.

Currencies should use ISO 4217 codes where possible.

Line items must preserve their original document order.

## Special schemas

A single `default_scheme.json` is used for all ten invoice documents. No special schema is needed here: VAT/GST/TRN identifiers, discounts, freight, duty, lots, case-pack conversion, free-of-charge quantities, origin, carton, and split-shipment references are covered by the default schema.
