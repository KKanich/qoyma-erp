import json
import uuid
from datetime import timedelta

from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import ReceiptScanEvent, ReceiptScanSession, StockReceipt, Supplier, User
from .tests import make_product


class PhoneScannerTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_superuser('scan-admin', password='test-only')
        self.product = make_product()
        self.client.force_login(self.owner)
        self.phone = Client()
        self.phone.force_login(self.owner)
        self.session = self.client.post(reverse('scanner_create'), '{}', content_type='application/json').json()
        self.sid = self.session['id']

    def post(self, name, data=None, client=None):
        return (client or self.client).post(reverse(name, args=[self.sid]),
            json.dumps(data or {}), content_type='application/json')

    def scan(self, request_id=None, barcode=None):
        return self.post('scanner_submit', {'request_id': str(request_id or uuid.uuid4()),
            'barcode': barcode or self.product.barcode}, self.phone)

    def test_phone_to_mac_acknowledgement_does_not_change_inventory(self):
        response = self.scan()
        self.assertEqual(response.status_code, 200)
        event = response.json()
        poll = self.post('scanner_poll').json()
        self.assertEqual(poll['events'], [{'id': event['id'], 'barcode': self.product.barcode}])
        self.assertEqual(self.post('scanner_ack', {'id': event['id'], 'status': 'applied',
            'message': 'Added to form'}).status_code, 200)
        self.assertEqual(self.phone.get(event['status_url']).json()['status'], 'applied')
        self.assertEqual(self.post('scanner_poll').json()['events'], [])
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, 20)
        self.assertFalse(StockReceipt.objects.exists())

    def test_retry_same_scan_is_idempotent_but_new_scan_adds_event(self):
        request_id = uuid.uuid4()
        a, b = self.scan(request_id), self.scan(request_id)
        self.assertEqual(a.json()['id'], b.json()['id'])
        self.assertEqual(ReceiptScanEvent.objects.count(), 1)
        self.scan()
        self.assertEqual(ReceiptScanEvent.objects.count(), 2)

    def test_other_user_and_cashier_cannot_access_pairing(self):
        other = User.objects.create_superuser('other', password='test-only')
        self.phone.force_login(other)
        self.assertEqual(self.scan().status_code, 404)
        self.assertEqual(self.phone.get(reverse('scanner_phone', args=[self.sid])).status_code, 404)
        self.assertEqual(self.post('scanner_poll', client=self.phone).status_code, 404)
        cashier = User.objects.create_user('scanner-cashier', role='Cashier')
        self.phone.force_login(cashier)
        self.assertEqual(self.scan().status_code, 403)
        self.phone.logout()
        self.assertEqual(self.scan().status_code, 401)
        self.assertEqual(self.phone.get(reverse('scanner_phone', args=[self.sid])).status_code, 302)

    def test_expired_closed_and_disconnected_sessions_reject_scans(self):
        ReceiptScanSession.objects.filter(pk=self.sid).update(heartbeat_at=timezone.now()-timedelta(seconds=30))
        self.assertEqual(self.scan().status_code, 409)
        self.post('scanner_poll')
        self.assertEqual(self.scan().status_code, 200)
        self.post('scanner_close')
        self.assertEqual(self.scan().status_code, 410)
        ReceiptScanSession.objects.filter(pk=self.sid).update(closed=False, expires_at=timezone.now()-timedelta(seconds=1))
        self.assertEqual(self.scan().status_code, 410)
        self.assertEqual(self.post('scanner_poll').status_code, 410)

    def test_invalid_unknown_codes_and_bad_json_are_rejected(self):
        self.assertEqual(self.scan(barcode='123').status_code, 400)
        self.assertEqual(self.scan(barcode='0000000000000').status_code, 404)
        self.assertEqual(self.post('scanner_submit', {'barcode': self.product.barcode, 'request_id': 'bad'}).status_code, 400)
        self.assertEqual(self.client.post(reverse('scanner_submit', args=[self.sid]), '[1]', content_type='application/json').status_code, 400)
        self.assertFalse(ReceiptScanEvent.objects.exists())

    def test_ack_is_idempotent_and_sessions_are_isolated(self):
        event = self.scan().json()
        self.post('scanner_ack', {'id': event['id'], 'status': 'applied'})
        self.post('scanner_ack', {'id': event['id'], 'status': 'rejected'})
        self.assertEqual(ReceiptScanEvent.objects.get().status, 'applied')
        other_session = self.client.post(reverse('scanner_create'), '{}', content_type='application/json').json()
        self.assertEqual(self.client.post(other_session['poll_url']).json()['events'], [])

    @override_settings(SCANNER_PUBLIC_BASE_URL='https://erp.example.com')
    def test_pairing_link_qr_and_camera_page(self):
        session = self.client.post(reverse('scanner_create'), '{}', content_type='application/json').json()
        self.assertTrue(session['phone_ready'])
        self.assertTrue(session['phone_url'].startswith('https://erp.example.com/scanner/'))
        qr = self.client.get(session['qr_url'])
        self.assertEqual(qr.status_code, 200)
        self.assertEqual(qr['Content-Type'], 'image/svg+xml')
        page = self.phone.get(reverse('scanner_phone', args=[self.sid]))
        self.assertContains(page, 'camera-preview')
        self.assertContains(page, 'zxing-browser.min.js')
        self.assertEqual(page['Cache-Control'], 'no-store')

    def test_csrf_required_for_state_changes(self):
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.owner)
        self.assertEqual(strict.post(reverse('scanner_create')).status_code, 403)
        self.assertEqual(self.post('scanner_submit', client=strict).status_code, 403)

    def test_posted_receipt_cannot_be_paired(self):
        supplier = Supplier.objects.create(name='Supplier', phone='123')
        receipt = StockReceipt.objects.create(supplier=supplier, received_by=self.owner, posted=True)
        response = self.client.post(reverse('scanner_create'), json.dumps({'receipt_id': receipt.pk}), content_type='application/json')
        self.assertEqual(response.status_code, 400)
