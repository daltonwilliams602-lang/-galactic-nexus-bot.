"""Backup handles must close deterministically, including on Windows."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from nexus.storage import Store


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

    def test_rotation_preserves_progress_and_recent_verified_snapshots(self):
        folder = Path(self.tmp.name) / 'backups'
        self.store.put('member', '1', {'xp': 500, 'rank': 2})
        self.store.log('1', 'join', '1', None, {'accepted': True}, 'Joined')
        self.store.enqueue('roles', {'member': '1'}, ident='pending-role')
        self.store.seen('message-1')
        created = [self.store.backup(folder) for _ in range(15)]
        self.assertEqual(set(folder.iterdir()), set(created[-12:]))
        self.assertTrue(self.store.path.exists())
        with self.real_connect(created[-1]) as restored:
            self.assertEqual(restored.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            self.assertEqual(restored.execute('SELECT count(*) FROM audit').fetchone()[0], 1)
            self.assertEqual(restored.execute('SELECT count(*) FROM receipts').fetchone()[0], 1)
            self.assertEqual(restored.execute('SELECT count(*) FROM outbox WHERE delivered=0').fetchone()[0], 1)
        self.assertEqual(self.store.get('member', '1'), {'xp': 500, 'rank': 2})

    def test_rotation_preserves_activation_snapshots_and_unrelated_files(self):
        folder = Path(self.tmp.name) / 'backups'
        archived = self.store.backup(folder)
        paired_config = archived.with_name(archived.stem + '-config.json')
        paired_config.write_text('{}')
        unrelated = [folder / 'test-manual.sqlite3', folder / 'live-1.sqlite3',
                     folder / 'notes.txt']
        for path in unrelated:
            path.write_text('keep')
        for _ in range(15):
            self.store.backup(folder)
        self.assertTrue(archived.exists())
        self.assertTrue(paired_config.exists())
        self.assertTrue(all(path.read_text() == 'keep' for path in unrelated))

    def test_failed_backup_keeps_existing_snapshots_and_removes_partial(self):
        folder = Path(self.tmp.name) / 'backups'
        previous = [self.store.backup(folder) for _ in range(12)]
        failing_source = Mock()
        failing_source.backup.side_effect = sqlite3.OperationalError('Disk full')
        with patch.object(self.store, 'db', failing_source):
            with self.assertRaises(sqlite3.OperationalError):
                self.store.backup(folder)
        self.assertEqual(set(folder.iterdir()), set(previous))


if __name__ == '__main__':
    unittest.main()
