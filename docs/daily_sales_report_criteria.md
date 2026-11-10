# Daily Sales Report — Acceptance Criteria

Owner: Aizada Amanova (Systems Analysis & Requirements Lead)

## Goal
The manager sees how the store performed today: total sales, number of receipts,
payment methods, top products, and can download the sales as a CSV file.

## Users
- Manager, Admin - can open the report and download CSV
- Cashier — cannot open the report or download CSV
- Not logged in - redirected to the login page

## Acceptance criteria

### A. Dashboard - totals
| ID    | Criterion                                 | How to check                           
|-------|-------------------------------------------|-----------------------------------------------------
| AC-D1 | Report shows today's total sales amount   |Sell 2 Milk(1 100 ₸) + 1 Bread (190 ₸)→total = 1 290 ₸|
| AC-D2 | Report shows the number of receipts today |Make 3 sales → "Receipts: 3"                         
| AC-D3 | Report shows the average receipt amount   |Sales of 1 000 ₸ and 2 000 ₸ → average = 1 500 ₸      
| AC-D4 | Total is split by payment method (Cash/Kaspi/Card) | One Cash + one Kaspi QR sale → both amounts shown separately|

### B. Dashboard — products
| ID    | Criterion                                          | How to check     
| AC-D5 | Report shows top 5 products by quantity sold       | Milk sold 5, Bread sold 2 → Milk is first |
| AC-D6 | Report shows products with low stock               | Kefir stock 4, minimum 5 → Kefir is in the low-stock list  |

### C. Data correctness
| ID    | Criterion                              | How to check                        
|-------|----------------------------------------|
| AC-D7 | Only today's sales are counted         | A sale from yesterday is NOT included in today's total  
| AC-D8 | Report works when there are no sales   | No sales today → total 0 ₸, receipts 0, no error  

### D. CSV export
| ID     | Criterion                                          | How to check  
|--------|----------------------------------------------------|
| AC-D9  | CSV with today's sales can be downloadedи          | Click "Download CSV" → file sales_YYYY-MM-DD.csv is downloaded
| AC-D10 | CSV has one row per sold item with correct columns | Columns: sale_id, time, cashier, product, qty, unit_price, subtotal, payment |

### E. Access and Admin
| ID     | Criterion                                         | How to check  
|--------|------------------------------------------------|
|AC-D11|Cashier cannot open the report or CSV     |Cashier opens /report/ or /report/csv/ → 403 Forbidden
|AC-D12|Report can be opened from the Admin panel |Admin panel has a "Daily sales report" link→opens /report/