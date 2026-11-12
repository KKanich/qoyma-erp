from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from store.db_backup import database_path, snapshot


class Command(BaseCommand):
    help = 'Verify and restore a backup to a NEW file for an offline recovery drill.'
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument('backup', type=Path)
        parser.add_argument('--target', required=True, type=Path)

    def handle(self, *args, **options):
        if options['target'].resolve() == Path(database_path()).resolve():
           raise CommandError('Restore to a separate file, then follow backup/README.md for offline cutover.')
        result = snapshot(options['backup'], options['target'])
        self.stdout.write(self.style.SUCCESS(f'Restore verified: {result} (live database unchanged)'))
