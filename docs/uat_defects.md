# UAT Defects — Qoyma ERP

Found during UAT on 17 November 2026 (see `uat_scenario.md`). Tester: Aizada Amanova

| ID | UAT step | Problem | Severity | Owner | Status |
|----|----------|---------|----------|-------|--------|
| D-01 | 13 | CSV opens in Excel (Russian locale) with all data in column A: Excel expects `;` as the separator, the file uses `,` | Major | Aizada | Fixed |
| D-02 | 12 | Numbers have different formats on the report: "1100 ₸" next to "0.00" and "1100.00" | Minor | Aizada | Fixed |
| D-03 | 15 | Admin shows "Categorys" instead of "Categories" | Minor | Kanat | Open |
| D-04 | 5, 6 | 403 page is a plain white page with no design and no link back to POS | Minor | Adilet | Open |