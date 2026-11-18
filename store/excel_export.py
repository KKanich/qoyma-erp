
"""Daily sales report as a formatted Excel workbook (.xlsx).

Owner: Aizada Amanova (Systems Analysis & Requirements Lead)
Fixes UAT defect D-01: the CSV opened in one column in Excel.
The workbook has 3 sheets with styled tables and charts:
  Summary      — key numbers, payment methods (+ chart), low stock
  Sales        — every sold item, filter, totals row
  Top products — top 5 products (+ chart)
"""
from openpyxl import Workbook
from openpyxl.chart import BarChart, PieChart, Reference
from openpyxl.chart.label import DataLabelList
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

MONEY = '#,##0.00 "₸"'
QTY = '#,##0.##'
DARK = '1F3B57'
LIGHT = 'EAF1F8'
ACCENT = '2FBF71'

HEADER_FONT = Font(bold=True, color='FFFFFF')
HEADER_FILL = PatternFill('solid', fgColor=DARK)
ZEBRA_FILL = PatternFill('solid', fgColor=LIGHT)
THIN = Side(style='thin', color='C9D3DD')
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


def _num(value):
    return float(value) if value is not None else 0.0


def _table(ws, top, left, headers, rows, formats=None):
    """Write a styled table. Returns the last row number."""
    for i, title in enumerate(headers):
        cell = ws.cell(row=top, column=left + i, value=title)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(horizontal='center', vertical='center')
        cell.border = BORDER
    for r, row in enumerate(rows, start=1):
        for i, value in enumerate(row):
            cell = ws.cell(row=top + r, column=left + i, value=value)
            cell.border = BORDER
            if r % 2 == 0:
                cell.fill = ZEBRA_FILL
            if formats and formats[i]:
                cell.number_format = formats[i]
    return top + len(rows)


def _widths(ws, widths):
    for i, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = width


def build_sales_workbook(summary, items, payment_labels, store_name='Bereke Grocery Store'):
    """summary: result of daily_sales_summary(); items: list of dicts from sales_rows()."""
    day = summary['day']
    wb = Workbook()

    # ---------- Sheet 1: Summary ----------
    ws = wb.active
    ws.title = 'Summary'
    ws['A1'] = f'Daily sales report — {store_name}'
    ws['A1'].font = Font(bold=True, size=16, color=DARK)
    ws['A2'] = f'Date: {day:%d.%m.%Y}'
    ws['A2'].font = Font(italic=True, color='667788')

    kpis = [('Total sales', _num(summary['total']), MONEY),
            ('Receipts', summary['receipts'], '0'),
            ('Average receipt', _num(summary['average']), MONEY)]
    for i, (label, value, fmt) in enumerate(kpis):
        col = 1 + i * 2
        top = ws.cell(row=4, column=col, value=label)
        top.font = Font(color='667788')
        val = ws.cell(row=5, column=col, value=value)
        val.font = Font(bold=True, size=18, color=DARK)
        val.number_format = fmt

    ws['A7'] = 'By payment method'
    ws['A7'].font = Font(bold=True, size=12, color=DARK)
    total = _num(summary['total'])
    pay_rows = [(payment_labels.get(code, code), _num(amount),
                 (_num(amount) / total) if total else 0)
                for code, amount in summary['by_payment'].items()]
    last = _table(ws, 8, 1, ['Method', 'Amount, ₸', 'Share'], pay_rows, [None, MONEY, '0%'])
    total_row = last + 1
    ws.cell(row=total_row, column=1, value='Total').font = Font(bold=True)
    cell = ws.cell(row=total_row, column=2, value=f'=SUM(B9:B{last})')
    cell.font = Font(bold=True)
    cell.number_format = MONEY

    if total:
        pie = PieChart()
        pie.title = 'Sales by payment method'
        pie.add_data(Reference(ws, min_col=2, min_row=8, max_row=last), titles_from_data=True)
        pie.set_categories(Reference(ws, min_col=1, min_row=9, max_row=last))
        pie.dataLabels = DataLabelList()
        pie.dataLabels.showPercent = True
        pie.dataLabels.showVal = False
        pie.dataLabels.showCatName = False
        pie.dataLabels.showSerName = False
        pie.dataLabels.showLegendKey = False
        pie.height, pie.width = 7.5, 11
        ws.add_chart(pie, 'E7')

    low_top = total_row + 3
    ws.cell(row=low_top - 1, column=1, value='Low stock (at or below minimum)').font = Font(bold=True, size=12, color=DARK)
    low_rows = [(p['name'], _num(p['quantity']), _num(p['min_quantity'])) for p in summary['low_stock']]
    if low_rows:
        _table(ws, low_top, 1, ['Product', 'In stock', 'Minimum'], low_rows, [None, QTY, QTY])
    else:
        ws.cell(row=low_top, column=1, value='All products are above minimum')
    _widths(ws, [30, 16, 16, 4, 16, 4])

    # ---------- Sheet 2: Sales ----------
    ws2 = wb.create_sheet('Sales')
    headers = ['Receipt #', 'Time', 'Cashier', 'Product', 'Qty', 'Unit price, ₸', 'Subtotal, ₸', 'Payment']
    rows = [(i['sale_id'], i['time'], i['cashier'], i['product'], _num(i['qty']),
             _num(i['unit_price']), _num(i['subtotal']), payment_labels.get(i['payment'], i['payment']))
            for i in items]
    last = _table(ws2, 1, 1, headers, rows, [None, None, None, None, QTY, MONEY, MONEY, None])
    if rows:
        tr = last + 1
        ws2.cell(row=tr, column=4, value='Total').font = Font(bold=True)
        for col, fmt in ((5, QTY), (7, MONEY)):
            letter = get_column_letter(col)
            cell = ws2.cell(row=tr, column=col, value=f'=SUM({letter}2:{letter}{last})')
            cell.font = Font(bold=True)
            cell.number_format = fmt
        ws2.auto_filter.ref = f'A1:H{last}'
    else:
        ws2.cell(row=2, column=1, value='No sales today')
    ws2.freeze_panes = 'A2'
    _widths(ws2, [11, 9, 14, 30, 8, 15, 15, 12])

    # ---------- Sheet 3: Top products ----------
    ws3 = wb.create_sheet('Top products')
    top_rows = [(p['product__name'], _num(p['qty']), _num(p['amount'])) for p in summary['top_products']]
    last = _table(ws3, 1, 1, ['Product', 'Qty sold', 'Amount, ₸'], top_rows, [None, QTY, MONEY])
    if top_rows:
        bar = BarChart()
        bar.type = 'bar'
        bar.title = 'Top products by quantity'
        bar.legend = None
        bar.add_data(Reference(ws3, min_col=2, min_row=1, max_row=last), titles_from_data=True)
        bar.set_categories(Reference(ws3, min_col=1, min_row=2, max_row=last))
        bar.series[0].graphicalProperties.solidFill = ACCENT
        bar.dataLabels = DataLabelList()
        bar.dataLabels.showVal = True
        bar.dataLabels.showCatName = False
        bar.dataLabels.showSerName = False
        bar.dataLabels.showLegendKey = False
        bar.x_axis.scaling.orientation = 'maxMin'  # biggest seller on top
        bar.y_axis.crosses = 'max'  # value axis at the bottom
        bar.x_axis.delete = False
        bar.y_axis.delete = False
        bar.height, bar.width = 7.5, 14
        ws3.add_chart(bar, 'E2')
    else:
        ws3.cell(row=2, column=1, value='No sales today')
    _widths(ws3, [30, 12, 15])

    return wb
