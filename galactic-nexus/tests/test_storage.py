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


if __name__ == '__main__':
    unittest.main()
