"""Tests for the in-app Help page (/help/)."""
from django.test import TestCase
from django.urls import reverse

from .models import User


class HelpPageTest(TestCase):

    def test_every_role_can_open_help(self):
        """Cashier, Manager and Admin all see the user guide."""
        for role in ('Cashier', 'Manager', 'Admin'):
            user = User.objects.create_user(role.lower(), password='pass12345', role=role)
            self.client.force_login(user)
            res = self.client.get(reverse('help_page'))
            self.assertEqual(res.status_code, 200)
            self.assertContains(res, 'User Guide')
            self.assertContains(res, 'store/help/pos.png')

    def test_not_logged_in_is_redirected_to_login(self):
        """Anonymous user is sent to the login page."""
        res = self.client.get(reverse('help_page'))
        self.assertEqual(res.status_code, 302)
        self.assertIn('/login/', res['Location'])

    def test_pos_has_help_link_for_cashier(self):
        """The Help link is on the POS screen, also for the cashier."""
        cashier = User.objects.create_user('cashier', password='pass12345', role='Cashier')
        self.client.force_login(cashier)
        self.assertContains(self.client.get(reverse('pos_page')), 'href="/help/"')

    def test_help_does_not_show_passwords(self):
        """The guide inside the system must not show demo passwords."""
        cashier = User.objects.create_user('cashier', password='pass12345', role='Cashier')
        self.client.force_login(cashier)
        res = self.client.get(reverse('help_page'))
        self.assertNotContains(res, 'QoymaAdmin2026')
