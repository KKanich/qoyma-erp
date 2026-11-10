"""Verified SQLite snapshots shared by backup and recovery commands."""
import os
import sqlite3
import tempfile
import time
from contextlib import closing
from pathlib import Path

from django.conf import settings
from django.core.management.base import CommandError


def database_path():
    config = settings.DATABASES['default']
    name = str(config['NAME'])
    if config['ENGINE'] != 'django.db.backends.sqlite3' or name == ':memory:' or name.startswith('file:'):
        raise CommandError('Backup requires a file-based SQLite default database.')
    return Path(name).resolve()


def snapshot(source, target, timeout=60):
    """Publish a checked snapshot without overwriting any existing target."""
    source, target = Path(source).resolve(), Path(target).resolve()
    if source == target or target.exists():
        raise CommandError(f'Refusing to overwrite: {target}')
    if not source.is_file():
        raise CommandError(f'Source database does not exist: {source}')
    temporary = None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix='.snapshot-', suffix='.tmp', dir=target.parent)
        os.close(fd)
        deadline = time.monotonic() + timeout

        def progress(status, remaining, total):
            if time.monotonic() > deadline:
                raise CommandError(f'Snapshot exceeded {timeout} seconds; retry during a quieter period.')

        with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as src:
            with closing(sqlite3.connect(temporary)) as dest:
                src.backup(dest, pages=256, progress=progress, sleep=0.1)
                # Produce a standalone file even when the source uses WAL.
                dest.execute('PRAGMA journal_mode=DELETE')
                if dest.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
                    raise CommandError('Snapshot failed SQLite integrity_check.')
                if dest.execute('PRAGMA foreign_key_check').fetchone() is not None:
                    raise CommandError('Snapshot contains foreign-key violations.')
                if not dest.execute("SELECT 1 FROM sqlite_master WHERE type='table'").fetchone():
                    raise CommandError('Source has no tables; run migrations before backing up.')
        with open(temporary, 'r+b') as stream:
            os.fsync(stream.fileno())
        # An atomic, no-clobber publication: failure leaves no partial final file.
        os.link(temporary, target)
    except (OSError, sqlite3.Error) as exc:
        raise CommandError(f'Snapshot failed: {exc}') from exc
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)
    return target
