(() => {
    'use strict';
    const input = document.getElementById('receipt-barcode');
    if (!input) return;
    const products = new Map(JSON.parse(document.getElementById('receipt-scan-products').textContent)
        .map(product => [product.barcode, product]));
    const status = document.getElementById('receipt-scan-status');
    const group = document.getElementById('items-group');
    const rows = () => [...group.querySelectorAll('.inline-related tbody tr.form-row')]
        .filter(row => !row.classList.contains('empty-form') && !row.querySelector('input[name$="-DELETE"]')?.checked);
    const select = row => row.querySelector('select[name$="-product"]');
    const quantity = row => row.querySelector('input[name$="-quantity"]');
    function scan() {
        const barcode = input.value.trim();
        if (!/^\d{13}$/.test(barcode)) {
            status.textContent = 'Введите штрихкод из 13 цифр.';
            input.select();
            return;
        }
        const product = products.get(barcode);
        if (!product) {
            status.textContent = 'Товар не найден. Создайте карточку товара через «+» рядом с Product, затем отсканируйте снова после открытия новой формы прихода. Не перезагружайте несохранённый приход.';
            input.select();
            return;
        }
        let row = rows().find(row => select(row)?.value === String(product.id));
        if (row) {
            const field = quantity(row);
            const value = Number(field.value);
            if (!Number.isFinite(value) || value < 0 || value + 1 > 99999999.99) {
                status.textContent = 'Исправьте количество в строке товара перед сканированием.';
                return;
            }
            field.value = (Math.round(value * 100) + 100) / 100;
        } else {
            row = rows().find(row => select(row)?.value === '' && !quantity(row)?.value && !row.querySelector('input[name$="-purchase_price"]')?.value);
            if (!row) {
                group.querySelector('.add-row a').click();
                row = rows().find(row => select(row)?.value === '');
            }
            if (!row) {
                status.textContent = 'Не удалось добавить строку. Проверьте лимит позиций.';
                return;
            }
            select(row).value = String(product.id);
            select(row).dispatchEvent(new Event('change', {bubbles: true}));
            quantity(row).value = '1';
        }
        quantity(row).dispatchEvent(new Event('change', {bubbles: true}));
        status.textContent = `${product.name}: количество ${quantity(row).value}. Проверьте закупочную цену.`;
        input.value = '';
        input.focus();
    }
    input.addEventListener('keydown', event => {
        if (event.key === 'Enter') {
            event.preventDefault();
            scan();
        }
    });
    document.getElementById('receipt-scan').addEventListener('click', scan);
})();
