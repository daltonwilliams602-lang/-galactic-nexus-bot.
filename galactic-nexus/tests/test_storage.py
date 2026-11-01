"""Backup handles must close deterministically, including on Windows."""
import sqlite3
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from nexus.storage import Store, prune_backups


class BackupHandleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / 'test.sqlite3')
        self.connections = []
        self.real_connect = sqlite3.connect

    def tearDown(self):
        for connection in self.connections:
            connection.close()
        self.store.close()
        self.tmp.cleanup()

    def capture_connection(self, *args, **kwargs):
        connection = self.real_connect(*args, **kwargs)
        # Hold a strong reference so garbage collection cannot conceal a leak.
        self.connections.append(connection)
        return connection

    def assert_destination_closed(self):
        self.assertEqual(len(self.connections), 1)
        with self.assertRaises(sqlite3.ProgrammingError):
            self.connections[0].execute('SELECT 1')

    def test_backup_closes_handle_before_returning(self):
        self.store.put('member', '1', {'xp': 500})
        with patch('nexus.storage.sqlite3.connect', side_effect=self.capture_connection):
            target = self.store.backup(Path(self.tmp.name) / 'backups')
        self.assert_destination_closed()
        # Windows must permit immediate rename/unlink, without a GC cycle.
        renamed = target.with_name('closed-backup.sqlite3')
        target.rename(renamed)
        restored = Store(renamed)
        try:
            self.assertEqual(restored.get('member', '1'), {'xp': 500})
        finally:
            restored.close()
        renamed.unlink()

    def test_backup_closes_handle_on_copy_failure(self):
        failing_source = Mock()
        failing_source.backup.side_effect = sqlite3.OperationalError('Simulated copy failure')
        with patch('nexus.storage.sqlite3.connect', side_effect=self.capture_connection):
            with patch.object(self.store, 'db', failing_source):
                with self.assertRaises(sqlite3.OperationalError):
                    self.store.backup(Path(self.tmp.name) / 'backups')
        self.assert_destination_closed()
        self.assertEqual(list((Path(self.tmp.name) / 'backups').iterdir()), [])


class BackupRetentionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.folder = self.root / 'backups'
        self.store = Store(self.root / 'live.sqlite3')
        self.store.put('member', 'fixture', {'xp': 12345, 'rank': 3})
        self.store.log('fixture', 'test', 'fixture', None, {'xp': 12345}, 'Keep history')
        self.seed = self.store.backup(self.folder)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def legacy_backups(self, count):
        for number in range(count):
            shutil.copyfile(self.seed, self.folder / f'live-{number + 1}.sqlite3')

    def test_repeated_backups_are_bounded_and_preserve_progress_and_audit(self):
        for _ in range(12):
            latest = self.store.backup(self.folder)
        self.assertEqual(len(list(self.folder.glob('live-*.sqlite3'))), 8)
        self.assertTrue(latest.is_file())
        restored = Store(latest)
        try:
            self.assertEqual(restored.get('member', 'fixture'), {'xp': 12345, 'rank': 3})
            self.assertEqual(restored.db.execute('SELECT COUNT(*) FROM audit').fetchone()[0], 1)
        finally:
            restored.close()

    def test_full_legacy_directory_prunes_read_only_and_keeps_verified_copies(self):
        self.legacy_backups(12)
        corrupt = self.folder / 'live-9999999999999999999.sqlite3'
        corrupt.write_bytes(b'incomplete backup')
        before = self.store.path.read_bytes()
        self.assertGreater(prune_backups(self.folder, 'live', budget=0), 0)
        remaining = list(self.folder.glob('live-*.sqlite3'))
        self.assertEqual(len(remaining), 2)
        self.assertFalse(corrupt.exists())
        for path in remaining:
            with sqlite3.connect(path) as db:
                self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
        self.assertEqual(self.store.path.read_bytes(), before)
        self.assertEqual(self.store.get('member', 'fixture')['xp'], 12345)

    def test_archives_other_database_and_unrecognized_files_are_preserved(self):
        self.legacy_backups(12)
        archive = self.folder / 'live-1.sqlite3'
        archive.with_name(archive.stem + '-config.json').write_text('{}')
        names = ['test-1.sqlite3', 'manual.sqlite3', 'server-before-1.json', 'live-not-a-time.sqlite3']
        for name in names:
            (self.folder / name).write_text('preserve')
        sidecar_copy = self.folder / 'live-2.sqlite3'
        Path(str(sidecar_copy) + '-wal').write_text('preserve')
        link = self.folder / 'live-3.sqlite3'
        link.unlink()
        link.symlink_to(self.store.path)
        prune_backups(self.folder, 'live', budget=0)
        self.assertTrue(archive.exists())
        self.assertTrue(sidecar_copy.exists())
        self.assertTrue(link.is_symlink())
        for name in names:
            self.assertEqual((self.folder / name).read_text(), 'preserve')

    def test_no_deletion_without_two_verified_recovery_copies(self):
        for number in range(12):
            (self.folder / f'live-{number}.sqlite3').write_bytes(b'broken')
        before = sorted(p.name for p in self.folder.iterdir())
        self.assertEqual(prune_backups(self.folder, 'live', budget=0), 0)
        self.assertEqual(sorted(p.name for p in self.folder.iterdir()), before)

    def test_failed_copy_leaves_existing_backups_and_no_partial_file(self):
        failing_source = Mock()
        failing_source.backup.side_effect = sqlite3.OperationalError('database or disk is full')
        before = sorted(p.name for p in self.folder.iterdir())
        with patch.object(self.store, 'db', failing_source):
            with self.assertRaisesRegex(sqlite3.OperationalError, 'disk is full'):
                self.store.backup(self.folder)
        self.assertEqual(sorted(p.name for p in self.folder.iterdir()), before)
        self.assertEqual(self.store.get('member', 'fixture')['xp'], 12345)


if __name__ == '__main__':
    unittest.main()
