from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.core.management.base import BaseCommand

from store.db_backup import database_path, snapshot


class Command(BaseCommand):
    help = 'Create an integrity-checked SQLite backup, safe while the app is running.'
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument('--output-dir', type=Path, default=settings.BASE_DIR / 'backup')

    def handle(self, *args, **options):
        timestamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        target = options['output_dir'] / f'qoyma-{timestamp}-{uuid4().hex[:8]}.sqlite3'
        result = snapshot(database_path(), target)
        self.stdout.write(self.style.SUCCESS(f'Backup verified: {result}'))
