(() => {
    'use strict';
    const root = document.getElementById('phone-scanner');
    const message = document.getElementById('scan-message');
    const start = document.getElementById('camera-start');
    const stop = document.getElementById('camera-stop');
    const retry = document.getElementById('scan-retry');
    const manual = document.getElementById('manual-send');
    const csrf = document.querySelector('[name=csrfmiddlewaretoken]').value;
    const video = document.getElementById('camera-preview');
    // Own the stream and the decode loop: ZXing's built-in loop silently stops the stream
    // (black preview on iPhone) after any unexpected per-frame error.
    let stream = null, scanTimer = null, reader = null, canvas = null, context = null;
    const stats = document.getElementById('scan-stats');
    let frames = 0;
    // EAN-13 only + TRY_HARDER (more rows, also tries the frame rotated 90°).
    // Numeric keys = ZXing DecodeHintType: 2 = POSSIBLE_FORMATS, 3 = TRY_HARDER.
    function createReader() {
        const hints = new Map([[2, [ZXingBrowser.BarcodeFormat.EAN_13]], [3, true]]);
        return new ZXingBrowser.BrowserMultiFormatOneDReader(hints);
    }
    let starting = false, armed = true, pending = null, timer = null, busy = false;
    const id = () => (crypto.randomUUID ? crypto.randomUUID()
        : '10000000-1000-4000-8000-100000000000'.replace(/[018]/g, c =>
            (c ^ crypto.getRandomValues(new Uint8Array(1))[0] & 15 >> c / 4).toString(16)));
    function stopCamera() {
        clearTimeout(scanTimer); scanTimer = null;
        stream?.getTracks().forEach(track => track.stop()); stream = null;
        video.srcObject = null;
        if (stats) stats.textContent = '';
        stop.hidden = true; start.disabled = false;
    }
    function waitForFrames(timeout = 8000) {
        return new Promise((resolve, reject) => {
            const began = Date.now();
            (function check() {
                if (!stream) return reject(Object.assign(new Error('stopped'), {name: 'AbortError'}));
                if (video.videoWidth > 0 && video.readyState >= 2) return resolve();
                if (Date.now() - began > timeout) return reject(Object.assign(new Error('no frames'), {name: 'NoFramesError'}));
                setTimeout(check, 100);
            })();
        });
    }
    function scanFrame() {
        if (!stream) return;
        frames += 1;
        if (stats && frames % 4 === 0 && !stats.dataset.soundHint) stats.textContent = `Камера сканирует… кадров: ${frames}`;
        try {
            const scale = Math.min(1, 1600 / Math.max(video.videoWidth, video.videoHeight));
            const width = Math.round(video.videoWidth * scale), height = Math.round(video.videoHeight * scale);
            if (width > 0 && height > 0 && !document.hidden) {
                // Every other frame is rotated 90°, so a barcode held vertically is read too
                // (ZXing's own TRY_HARDER rotation does not work in this build).
                const rotate = frames % 2 === 1;
                const cw = rotate ? height : width, ch = rotate ? width : height;
                if (canvas.width !== cw || canvas.height !== ch) { canvas.width = cw; canvas.height = ch; }
                context.setTransform(1, 0, 0, 1, 0, 0);
                if (rotate) { context.translate(cw / 2, ch / 2); context.rotate(-Math.PI / 2); context.translate(-width / 2, -height / 2); }
                context.drawImage(video, 0, 0, width, height);
                const result = reader.decodeFromCanvas(canvas);
                if (result) captured(result.getText());
            }
        } catch (error) { /* no barcode in this frame (or a transient frame error): keep scanning */ }
        scanTimer = setTimeout(scanFrame, 250);
    }
    function cameraError(error) {
        const reasons = {
            NotAllowedError: 'Доступ к камере запрещён. iPhone: Настройки → Safari → Камера → «Разрешить», затем обновите страницу.',
            NotFoundError: 'Камера не найдена.',
            NotReadableError: 'Камера занята другим приложением. Закройте его и попробуйте снова.',
            OverconstrainedError: 'Камера не поддерживает нужный режим.',
            NoFramesError: 'Камера включилась, но не передаёт изображение. Нажмите «Включить камеру» ещё раз или откройте страницу в Safari.',
        };
        return reasons[error?.name] || `Камера недоступна (${error?.name || 'ошибка'}: ${error?.message || ''}).`;
    }
    async function json(url, options = {}) {
        const response = await fetch(url, {credentials: 'same-origin', ...options});
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw Object.assign(new Error(data.error || 'Соединение прервано. Войдите под тем же пользователем, что на Mac.'), {status: response.status});
        return data;
    }
    // --- Sounds -----------------------------------------------------------------------------
    // <audio> elements with generated WAV beeps: unlike Web Audio, media elements on iPhone
    // still play when the ring/silent switch is set to silent. iOS lets an element play
    // later only after it was started once inside a user tap, hence unlockSound().
    function wav(tones) {
        const rate = 22050, samples = [];
        for (const [freq, ms] of tones) {
            const n = Math.round(rate * ms / 1000);
            for (let i = 0; i < n; i++) {
                const env = Math.min(1, i / 200, (n - i) / 400); // soft attack/release, no clicks
                samples.push(freq ? Math.sin(2 * Math.PI * freq * i / rate) * env * 0.6 : 0);
            }
        }
        const buffer = new ArrayBuffer(44 + samples.length * 2), view = new DataView(buffer);
        const text = (offset, s) => [...s].forEach((ch, i) => view.setUint8(offset + i, ch.charCodeAt(0)));
        text(0, 'RIFF'); view.setUint32(4, 36 + samples.length * 2, true); text(8, 'WAVE');
        text(12, 'fmt '); view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
        view.setUint32(24, rate, true); view.setUint32(28, rate * 2, true); view.setUint16(32, 2, true); view.setUint16(34, 16, true);
        text(36, 'data'); view.setUint32(40, samples.length * 2, true);
        samples.forEach((s, i) => view.setInt16(44 + i * 2, s * 0x7fff, true));
        return URL.createObjectURL(new Blob([buffer], {type: 'audio/wav'}));
    }
    const sounds = {
        ok: new Audio(wav([[1046, 90], [0, 30], [1568, 160]])),   // bright two-note "done"
        error: new Audio(wav([[330, 180], [0, 60], [247, 260]])),  // low two-note "no"
    };
    let soundUnlocked = false;
    function unlockSound() {
        if (soundUnlocked) return;
        soundUnlocked = true;
        for (const audio of Object.values(sounds)) {
            audio.muted = true;
            audio.play().then(() => { audio.pause(); audio.currentTime = 0; audio.muted = false; })
                .catch(() => { audio.muted = false; soundUnlocked = false; });
        }
        if (stats?.dataset.soundHint) { delete stats.dataset.soundHint; stats.textContent = ''; }
    }
    function feedback(kind) {
        try { const audio = sounds[kind]; audio.currentTime = 0; audio.play().catch(() => {}); } catch (ignored) { /* no sound */ }
        navigator.vibrate?.(kind === 'ok' ? 80 : [120, 80, 120]); // Android; iPhone browsers ignore it
        message.classList.remove('ok', 'error'); void message.offsetWidth; message.classList.add(kind);
    }
    // --- Continuous scanning ------------------------------------------------------------------
    // The camera stays on. After Mac answers, the scanner re-arms by itself. The same code is
    // counted again only after it has been out of view for REPEAT_GAP_MS, so a barcode held in
    // front of the camera adds one unit, not one per frame. A different code is accepted at once.
    const REPEAT_GAP_MS = 1500;
    let lastCode = null, lastSeenAt = 0;
    function rearm() {
        armed = true; manual.disabled = false;
    }
    function completed(event) {
        pending = null;
        const applied = event.status === 'applied';
        message.textContent = applied ? `✓ Добавлено на Mac. ${event.message}` : `✗ Не добавлено: ${event.message}`;
        feedback(applied ? 'ok' : 'error');
        retry.hidden = true;
        rearm();
    }
    async function awaitMac(url, attempts = 0) {
        try {
            const event = await json(url);
            if (event.status !== 'pending') { completed(event); return; }
            if (attempts >= 30) throw new Error('Нет подтверждения Mac. Откройте вкладку прихода и повторите отправку.');
            timer = setTimeout(() => awaitMac(url, attempts + 1), 1000);
        } catch (error) { failure(error); }
    }
    function failure(error) {
        message.textContent = error.message;
        feedback('error');
        if ([400, 404].includes(error.status)) { pending = null; rearm(); }
        else if ([401, 403, 410].includes(error.status)) {
            pending = null; stopCamera(); manual.disabled = true; start.disabled = true;
        } else { retry.hidden = false; }
    }
    async function send() {
        if (!pending || busy) return;
        busy = true; retry.hidden = true;
        try {
            const event = await json(root.dataset.submitUrl, {method: 'POST',
                headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf}, body: JSON.stringify(pending)});
            if (event.status !== 'pending') completed(event);
            else { message.textContent = 'Код отправлен. Ожидаем добавления на Mac…'; awaitMac(event.status_url); }
        } catch (error) { failure(error); }
        finally { busy = false; }
    }
    function captured(barcode, {fromCamera = true} = {}) {
        const now = Date.now();
        if (fromCamera && barcode === lastCode && now - lastSeenAt < REPEAT_GAP_MS) {
            lastSeenAt = now; // still in view: keep the same code blocked
            return;
        }
        if (!armed || pending || busy) return;
        if (!/^\d{13}$/.test(barcode)) { message.textContent = 'Поддерживаются штрихкоды EAN-13 (13 цифр).'; feedback('error'); return; }
        lastCode = barcode; lastSeenAt = now;
        armed = false; manual.disabled = true;
        pending = {barcode, request_id: id()};
        message.textContent = `Распознан ${barcode}. Отправляем…`;
        send();
    }
    async function startCamera() {
        if (starting || stream) return;
        if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
            message.textContent = 'Камера требует HTTPS. Откройте защищённую ссылку с Mac.'; return;
        }
        if (!window.ZXingBrowser) { message.textContent = 'Не загрузилась библиотека камеры. Обновите страницу.'; return; }
        starting = true; start.disabled = true;
        message.textContent = 'Включаем камеру…';
        try {
            reader = reader || createReader();
            canvas = canvas || document.createElement('canvas');
            context = context || canvas.getContext('2d', {willReadFrequently: true}) || canvas.getContext('2d');
            stream = await navigator.mediaDevices.getUserMedia({audio: false, video: {
                facingMode: {ideal: 'environment'}, width: {ideal: 1920}, height: {ideal: 1080}}});
            const track = stream.getVideoTracks()[0];
            try { // Continuous autofocus where the browser exposes it (ignored elsewhere).
                const caps = track.getCapabilities?.() || {};
                if (caps.focusMode?.includes('continuous')) await track.applyConstraints({advanced: [{focusMode: 'continuous'}]});
            } catch (ignored) { /* optional */ }
            video.muted = true; video.playsInline = true;
            video.setAttribute('playsinline', ''); video.setAttribute('autoplay', '');
            video.srcObject = stream;
            await video.play();
            await waitForFrames();
            stop.hidden = false;
            message.textContent = 'Сканер работает: наводите на штрихкоды по очереди (15–25 см, поперёк красной линии).';
            frames = 0;
            if (document.hidden) stopCamera(); else scanFrame();
        } catch (error) {
            const wasStopped = error?.name === 'AbortError' && !stream;
            stopCamera();
            if (!wasStopped) message.textContent = cameraError(error);
        } finally { starting = false; }
    }
    start.addEventListener('click', () => { unlockSound(); startCamera(); });
    stop.addEventListener('click', stopCamera);
    retry.addEventListener('click', send); // Same request_id: retry cannot duplicate the scan.
    manual.addEventListener('click', () => {
        unlockSound();
        captured(document.getElementById('manual-code').value.trim(), {fromCamera: false});
    });
    // Any tap enables sound (iOS requirement), e.g. after the camera auto-started.
    document.addEventListener('pointerdown', unlockSound, {passive: true});
    document.addEventListener('visibilitychange', () => { if (document.hidden) stopCamera(); });
    // Start the camera without a tap when the permission was already granted before.
    navigator.permissions?.query({name: 'camera'}).then(status => {
        if (status.state === 'granted' && !document.hidden) {
            if (stats && !soundUnlocked) { stats.dataset.soundHint = '1'; stats.textContent = '🔇 Коснитесь экрана, чтобы включить звук'; }
            startCamera();
        }
    }).catch(() => { /* Permissions API not available: use the button */ });
    window.addEventListener('pagehide', () => { stopCamera(); clearTimeout(timer); });
})();
