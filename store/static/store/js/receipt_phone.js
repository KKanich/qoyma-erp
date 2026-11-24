(() => {
    'use strict';
    const panel = document.getElementById('phone-pairing');
    if (!panel) return;
    const connect = document.getElementById('phone-connect');
    const disconnect = document.getElementById('phone-disconnect');
    const status = document.getElementById('phone-status');
    const details = document.getElementById('phone-pair-details');
    const csrf = document.querySelector('[name=csrfmiddlewaretoken]').value;
    let session = null, timer = null, connecting = false;
    const handled = new Map();
    async function post(url, data = {}) {
        const response = await fetch(url, {method: 'POST', credentials: 'same-origin',
            headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf}, body: JSON.stringify(data)});
        const body = await response.json().catch(() => ({}));
        if (!response.ok) throw Object.assign(new Error(body.error || 'Ошибка соединения.'), {status: response.status});
        return body;
    }
    function close() {
        clearTimeout(timer);
        if (session) {
            const data = new FormData();
            data.append('csrfmiddlewaretoken', csrf);
            navigator.sendBeacon(session.close_url, data);
        }
        session = null;
        handled.clear();
        details.hidden = true;
        disconnect.hidden = true;
        connect.disabled = false;
    }
    async function poll(current) {
        if (session !== current) return;
        try {
            const data = await post(current.poll_url);
            for (const event of data.events) {
                if (session !== current) return;
                if (!handled.has(event.id)) {
                    // Cache before acknowledgement: retrying a lost ACK never adds twice.
                    handled.set(event.id, window.qoymaScanBarcode(event.barcode));
                }
                const result = handled.get(event.id);
                await post(current.ack_url, {id: event.id, ...result});
                status.textContent = result.message;
            }
        } catch (error) {
            status.textContent = error.message;
            if ([401, 403, 404, 410].includes(error.status)) { close(); return; }
        }
        if (session === current) timer = setTimeout(() => poll(current), 1000);
    }
    connect.addEventListener('click', async () => {
        if (connecting || session) return;
        connecting = true;
        connect.disabled = true;
        try {
            session = await post(panel.dataset.createUrl, {receipt_id: panel.dataset.receiptId || null});
            const link = document.getElementById('phone-link');
            link.href = session.phone_url;
            link.textContent = session.phone_url;
            document.getElementById('phone-qr').src = session.qr_url;
            details.hidden = false;
            disconnect.hidden = false;
            status.textContent = session.phone_ready
                ? 'Отсканируйте QR-код камерой телефона и войдите под тем же пользователем.'
                : 'Для телефона нужен HTTPS-адрес. Настройте SCANNER_PUBLIC_BASE_URL и ALLOWED_HOSTS по README. localhost доступен только на Mac.';
            poll(session);
        } catch (error) { status.textContent = error.message; connect.disabled = false; }
        finally { connecting = false; }
    });
    disconnect.addEventListener('click', () => { close(); status.textContent = 'Телефон отключён.'; });
    // A new document/form gets a new pairing; no old events replay after navigation.
    window.addEventListener('pagehide', close);
    panel.closest('form').addEventListener('submit', close);
})();
