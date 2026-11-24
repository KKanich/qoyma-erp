"""Authenticated, expiring phone-to-admin scan relay. Never changes inventory."""
import json
import re
import uuid
from datetime import timedelta
from functools import wraps
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from .models import Product, ReceiptScanEvent, ReceiptScanSession, StockReceipt


def scanner_access(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        user = request.user
        if not user.is_authenticated:
            return JsonResponse({'error': 'Войдите в систему.'}, status=401)
        if not (user.is_active and user.is_staff and user.has_perm('store.add_stockreceipt')
                and user.has_perm('store.add_stockreceiptitem')):
            return JsonResponse({'error': 'Нет права на создание прихода.'}, status=403)
        response = view(request, *args, **kwargs)
        response['Cache-Control'] = 'no-store'
        response['Referrer-Policy'] = 'no-referrer'
        return response
    return wrapped


def payload(request):
    try:
        data = json.loads(request.body)
        return data if isinstance(data, dict) else {}
    except (ValueError, UnicodeDecodeError):
        return {}


def session_for(request, session_id):
    return get_object_or_404(ReceiptScanSession, pk=session_id, owner=request.user)


def inactive(session):
    return (session.closed or session.expires_at <= timezone.now()
            or (session.receipt_id and StockReceipt.objects.filter(pk=session.receipt_id, posted=True).exists()))


def phone_url(request, session):
    base = settings.SCANNER_PUBLIC_BASE_URL or request.build_absolute_uri('/').rstrip('/')
    return base + reverse('scanner_phone', args=[session.pk])


@require_POST
@scanner_access
def create_session(request):
    data = payload(request)
    receipt = None
    if data.get('receipt_id'):
        try:
            receipt = StockReceipt.objects.get(pk=int(data['receipt_id']), posted=False)
        except (ValueError, TypeError, StockReceipt.DoesNotExist):
            return JsonResponse({'error': 'Приход уже проведён или не найден.'}, status=400)
        if not request.user.has_perm('store.change_stockreceipt'):
            return JsonResponse({'error': 'Нет права изменять приход.'}, status=403)
    now = timezone.now()
    # Bound retained transient data without touching receipts or products.
    ReceiptScanSession.objects.filter(owner=request.user, expires_at__lt=now-timedelta(days=1)).delete()
    session = ReceiptScanSession.objects.create(owner=request.user, receipt=receipt,
        expires_at=now+timedelta(minutes=30), heartbeat_at=now)
    url = phone_url(request, session)
    parts = urlsplit(url)
    return JsonResponse({
        'id': str(session.pk), 'phone_url': url,
        'phone_ready': parts.scheme == 'https' and parts.hostname not in ('localhost', '127.0.0.1', '::1'),
        'qr_url': reverse('scanner_qr', args=[session.pk]),
        'poll_url': reverse('scanner_poll', args=[session.pk]),
        'ack_url': reverse('scanner_ack', args=[session.pk]),
        'close_url': reverse('scanner_close', args=[session.pk]),
    }, status=201)


@require_GET
@login_required
@scanner_access
def phone_page(request, session_id):
    session = session_for(request, session_id)
    if inactive(session):
        return HttpResponse('Сессия завершена. Подключите телефон заново на Mac.', status=410)
    return render(request, 'store/phone_scanner.html', {'scan_session': session})


@require_GET
@scanner_access
def qr_code(request, session_id):
    import qrcode
    import qrcode.image.svg
    session = session_for(request, session_id)
    if inactive(session):
        return HttpResponse(status=410)
    qr = qrcode.make(phone_url(request, session), image_factory=qrcode.image.svg.SvgPathImage)
    return HttpResponse(qr.to_string(), content_type='image/svg+xml')


@require_POST
@scanner_access
def poll(request, session_id):
    session = session_for(request, session_id)
    if inactive(session):
        return JsonResponse({'error': 'Сессия завершена. Подключите телефон заново.'}, status=410)
    ReceiptScanSession.objects.filter(pk=session.pk).update(heartbeat_at=timezone.now())
    events = list(session.events.filter(status='pending').order_by('id').values('id', 'barcode')[:50])
    return JsonResponse({'events': events})


@require_POST
@scanner_access
@transaction.atomic
def submit_scan(request, session_id):
    session = session_for(request, session_id)
    if inactive(session):
        return JsonResponse({'error': 'Сессия завершена.'}, status=410)
    data = payload(request)
    barcode = data.get('barcode')
    try:
        request_id = uuid.UUID(str(data.get('request_id')))
    except ValueError:
        return JsonResponse({'error': 'Некорректный идентификатор скана.'}, status=400)
    existing = session.events.filter(request_id=request_id).first()
    if existing:
        if existing.barcode != barcode:
            return JsonResponse({'error': 'Идентификатор уже использован для другого скана.'}, status=409)
        return event_response(existing)
    if session.heartbeat_at < timezone.now()-timedelta(seconds=20):
        return JsonResponse({'error': 'Нет связи с Mac. Откройте вкладку прихода и повторите отправку.'}, status=409)
    if not isinstance(barcode, str) or not re.fullmatch(r'[0-9]{13}', barcode):
        return JsonResponse({'error': 'Нужен штрихкод из 13 цифр.'}, status=400)
    if not Product.objects.filter(barcode=barcode).exists():
        return JsonResponse({'error': 'Товар не найден в каталоге. Создайте его карточку на Mac.'}, status=404)
    if session.events.filter(status='pending').count() >= 50:
        return JsonResponse({'error': 'Очередь заполнена. Проверьте вкладку на Mac.'}, status=409)
    event, _ = ReceiptScanEvent.objects.get_or_create(session=session, request_id=request_id,
                                                    defaults={'barcode': barcode})
    return event_response(event)


def event_response(event):
    return JsonResponse({'id': event.pk, 'status': event.status, 'message': event.message,
        'status_url': reverse('scanner_event', args=[event.session_id, event.pk])})


@require_GET
@scanner_access
def event_status(request, session_id, event_id):
    session = session_for(request, session_id)
    if inactive(session):
        return JsonResponse({'error': 'Сессия завершена.'}, status=410)
    return event_response(get_object_or_404(session.events, pk=event_id))


@require_POST
@scanner_access
def acknowledge(request, session_id):
    session = session_for(request, session_id)
    if inactive(session):
        return JsonResponse({'error': 'Сессия завершена.'}, status=410)
    data = payload(request)
    if type(data.get('id')) is not int or data.get('status') not in ('applied', 'rejected'):
        return JsonResponse({'error': 'Некорректное подтверждение.'}, status=400)
    event = get_object_or_404(session.events, pk=data['id'])
    session.events.filter(pk=event.pk, status='pending').update(
        status=data['status'], message=str(data.get('message', ''))[:250])
    return JsonResponse({'ok': True})


@require_POST
@scanner_access
def close_session(request, session_id):
    session = session_for(request, session_id)
    ReceiptScanSession.objects.filter(pk=session.pk).update(closed=True)
    return JsonResponse({'ok': True})
