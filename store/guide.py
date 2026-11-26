"""In-app user guide (Help page) for the store staff.

Owner: Aizada Amanova (Systems Analysis & Requirements Lead)
Content: docs/user_guide.md, shown inside the system at /help/.
"""
from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def help_page(request):
    """Every logged-in role (Cashier, Manager, Admin) can read the guide."""
    return render(request, 'store/help.html')
