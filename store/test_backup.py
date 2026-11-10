import sqlite3
from contextlib import closing
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase

from store.db_backup import snapshot


class DatabaseBackupTests(SimpleTestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.source = self.root / 'live.sqlite3'
        with closing(sqlite3.connect(self.source)) as conn:
            conn.execute('CREATE TABLE stock (id INTEGER PRIMARY KEY, quantity INTEGER)')
            conn.execute('INSERT INTO stock VALUES (1, 20)')
            conn.commit()

    def test_commands_round_trip_recovers_previous_data(self):
        with patch('store.management.commands.backup_db.database_path', return_value=self.source):
            call_command('backup_db', output_dir=self.root / 'copies', stdout=StringIO())
            call_command('backup_db', output_dir=self.root / 'copies', stdout=StringIO())
        copies = list((self.root / 'copies').glob('*.sqlite3'))
        self.assertEqual(len(copies), 2)
        with closing(sqlite3.connect(self.source)) as conn:
            conn.execute('DELETE FROM stock')
            conn.commit()
        restored = self.root / 'restored.sqlite3'
        with patch('store.management.commands.restore_db.database_path', return_value=self.source):
            call_command('restore_db', str(copies[0]), target=restored, stdout=StringIO())
        with closing(sqlite3.connect(restored)) as conn:
            self.assertEqual(conn.execute('SELECT * FROM stock').fetchall(), [(1, 20)])
        with closing(sqlite3.connect(self.source)) as conn:
            self.assertEqual(conn.execute('SELECT * FROM stock').fetchall(), [])

    def test_wal_commits_included_uncommitted_changes_excluded(self):
        with closing(sqlite3.connect(self.source)) as writer:
            writer.execute('PRAGMA journal_mode=WAL')
            writer.execute('UPDATE stock SET quantity=30')
            writer.commit()
            writer.execute('UPDATE stock SET quantity=99')
            target = snapshot(self.source, self.root / 'wal.sqlite3')
            with closing(sqlite3.connect(target)) as conn:
                self.assertEqual(conn.execute('SELECT quantity FROM stock').fetchone(), (30,))

    def test_existing_target_and_source_are_never_overwritten(self):
        original = self.source.read_bytes()
        with self.assertRaises(CommandError):
            snapshot(self.source, self.source)
        with patch('store.management.commands.restore_db.database_path', return_value=self.source):
            with self.assertRaises(CommandError):
                call_command('restore_db', str(self.source), target=self.source, stdout=StringIO())
        self.assertEqual(self.source.read_bytes(), original)

    def test_restore_refuses_configured_live_path_even_if_missing(self):
        live = self.root / 'missing-live.sqlite3'
        with patch('store.management.commands.restore_db.database_path', return_value=live):
            with self.assertRaises(CommandError):
                call_command('restore_db', str(self.source), target=live)
        self.assertFalse(live.exists())

    def test_missing_corrupt_and_empty_sources_leave_no_output(self):
        corrupt = self.root / 'corrupt.sqlite3'
        corrupt.write_bytes(b'not a database')
        empty = self.root / 'empty.sqlite3'
        empty.touch()
        for source in (self.root / 'missing.sqlite3', corrupt, empty):
            with self.subTest(source=source):
                with self.assertRaises(CommandError):
                    snapshot(source, self.root / 'output.sqlite3')
                self.assertFalse((self.root / 'output.sqlite3').exists())
                self.assertEqual(list(self.root.glob('.snapshot-*')), [])

    def test_foreign_key_violations_rejected(self):
        with closing(sqlite3.connect(self.source)) as conn:
            conn.execute('CREATE TABLE child (stock_id INTEGER REFERENCES stock(id))')
            conn.execute('INSERT INTO child VALUES (999)')
            conn.commit()
        with self.assertRaisesMessage(CommandError, 'foreign-key'):
            snapshot(self.source, self.root / 'invalid.sqlite3')
        self.assertFalse((self.root / 'invalid.sqlite3').exists())

    def test_timeout_cleans_up_partial_snapshot(self):
        with self.assertRaisesMessage(CommandError, 'exceeded'):
            snapshot(self.source, self.root / 'timeout.sqlite3', timeout=-1)
        self.assertEqual(list(self.root.glob('.snapshot-*')), [])
        self.assertFalse((self.root / 'timeout.sqlite3').exists())
