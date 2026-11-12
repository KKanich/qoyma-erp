"""Test that the Admin panel links to the daily sales report (AC-D12)."""
from django.test import TestCase
from django.urls import reverse

from .models import User


class AdminReportLinkTest(TestCase):

    def test_acd12_admin_index_has_report_link(self):
        """AC-D12: Admin home page shows links to /report/ and /report/csv/."""
        admin_user = User.objects.create_superuser('admin', password='pass12345', role='Admin')
        self.client.force_login(admin_user)
        res = self.client.get(reverse('admin:index'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'href="/report/"')
        self.assertContains(res, 'href="/report/csv/"')