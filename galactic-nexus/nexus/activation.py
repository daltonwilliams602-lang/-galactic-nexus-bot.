"""Explicit, restart-safe launch preserving the founder database and its history."""
from contextlib import closing
import json
import os
from pathlib import Path
import shutil
import sqlite3
import time
import uuid

from .engine import Engine
from .storage import Store

LAUNCH_CONFIRMATION = 'OPEN GALACTIC NEXUS PRESERVE DATA'


def validate_live(config, database):
    """Read-only validation: never silently create an empty production database."""
    if not config.get('owner_approved_launch') or not Path(database).is_file():
        raise RuntimeError('Live mode requires recorded activation and its existing live database.')
    with closing(sqlite3.connect(f'{Path(database).resolve().as_uri()}?mode=ro', uri=True)) as db:
        rows = dict(db.execute("SELECT id,data FROM objects WHERE kind='meta' AND id IN ('deployment','activation')"))
    identity = {'guild_id': str(config['guild_id']), 'mode': 'live'}
    activation = json.loads(rows.get('activation', '{}'))
    if (json.loads(rows.get('deployment', '{}')) != identity
            or not activation.get('id') or activation.get('id') != config.get('activation_id')
            or activation.get('owner_id') != str(config['owner_id'])):
        raise RuntimeError('Live configuration does not match its recorded activation.')


def activate(config_path, config, confirmation):
    """Caller holds the volume lock. Copy once, then atomically select live state.

    Publishing live.sqlite3 freezes the original test database. If interrupted
    before selecting it in config, another activate resumes from its committed
    marker; ordinary test startup refuses to change the archived source.
    """
    from .launch import write_json
    if confirmation != LAUNCH_CONFIRMATION:
        raise RuntimeError('Activation requires NEXUS_LAUNCH_CONFIRMATION=OPEN GALACTIC NEXUS PRESERVE DATA.')
    live = Path(config['database_dir']) / 'live.sqlite3'
    if config['mode'] == 'live':
        validate_live(config, live)
        return config
    source = live.with_name('test.sqlite3')
    if not source.is_file():
        raise RuntimeError('Existing test database is required; no empty live database was created.')
    if len(set(config['founder_ids'])) != 4 or str(config['owner_id']) not in config['founder_ids']:
        raise RuntimeError('All four founders, including the owner, must be configured before activation.')
    if not config.get('role_ids') or not config.get('channel_ids'):
        raise RuntimeError('Complete server configuration before activation.')
    if not live.exists():
        store = Store(source)
        try:
            if store.get('meta', 'deployment') != {'guild_id': str(config['guild_id']), 'mode': 'test'}:
                raise RuntimeError('Source database does not match this test server.')
            if store.db.execute('SELECT COUNT(*) FROM outbox WHERE delivered=0').fetchone()[0]:
                raise RuntimeError('Drain the test delivery queue before activation to keep test messages private.')
            backup = store.backup(config['backup_dir'])
        finally:
            store.close()
        write_json(Path(config['backup_dir']) / (backup.stem+'-config.json'), config)
        # A fresh temporary name avoids reusing any interrupted SQLite WAL files.
        staged = live.with_name('activation-'+uuid.uuid4().hex+'.sqlite3')
        shutil.copyfile(backup, staged)
        os.chmod(staged, 0o600)
        copy = Store(staged)
        try:
            marker = {'id': uuid.uuid4().hex, 'owner_id': str(config['owner_id']),
                      'at': time.time(), 'source_backup': backup.name, 'preserve_data': True}
            with copy.transaction():
                copy.put('meta', 'deployment', {'guild_id': str(config['guild_id']), 'mode': 'live'})
                copy.put('meta', 'activation', marker)
                for key, item in copy.all('confirmation').items():
                    if not item.get('used'):
                        copy.put('confirmation', key, item | {'used': True, 'expired_at_launch': True})
                for key, item in copy.all('voice-check').items():
                    copy.put('voice-check', key, item | {'until': 0})
                copy.log(config['owner_id'], 'activate-live', config['guild_id'],
                         {'mode': 'test'}, marker, 'Owner approved opening; preserve existing progress and history.')
                Engine(copy, config | {'mode': 'live', 'owner_approved_launch': True})
            if copy.db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise RuntimeError('Live copy failed integrity check; source is unchanged.')
            copy.db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        finally:
            copy.close()
        os.replace(staged, live)
    # Recovery reads the committed marker but never overwrites an existing live DB.
    with closing(sqlite3.connect(f'{live.resolve().as_uri()}?mode=ro', uri=True)) as db:
        row = db.execute("SELECT data FROM objects WHERE kind='meta' AND id='activation'").fetchone()
    if not row:
        raise RuntimeError('Existing live database has no activation marker; refusing to replace it.')
    marker = json.loads(row[0])
    updated = config | {'mode': 'live', 'owner_approved_launch': True, 'activation_id': marker.get('id')}
    validate_live(updated, live)
    write_json(config_path, updated)
    print('LIVE ACTIVATION COMPLETE: existing XP, ranks, reviews, campaigns, receipts and history preserved.', flush=True)
    return updated
