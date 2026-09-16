"""Unattended bot worker with state kept on a required mounted volume."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import re
import signal
import sys

import discord

from .bot import run_bot
from .launch import configure, instance_lock, write_json
from .storage import Store
from .activation import activate, validate_live

SETUP_CONFIRMATION = 'CONFIGURE PRIVATE TEST SERVER'
SEED_CONFIG = Path(__file__).resolve().parents[1] / 'config.example.json'


def is_mounted(path):
    if path.is_mount():
        return True
    # Linux bind mounts on the same device are not detected by os.path.ismount.
    try:
        for line in Path('/proc/self/mountinfo').read_text().splitlines():
            fields = line.split()
            mount = re.sub(r'\\([0-7]{3})', lambda m: chr(int(m.group(1), 8)), fields[4])
            if Path(mount) == path:
                return True
    except (OSError, IndexError):
        pass
    return False


def mounted_data_dir(environ):
    raw = Path(environ.get('NEXUS_DATA_DIR', '/data'))
    if not raw.is_absolute():
        raise RuntimeError('NEXUS_DATA_DIR must be an absolute volume mount path, normally /data.')
    root = raw.resolve()
    if root == Path('/'):
        raise RuntimeError('Use a dedicated persistent volume at /data, not the container root.')
    if environ.get('RAILWAY_SERVICE_ID') or environ.get('RAILWAY_PROJECT_ID'):
        railway_mount = environ.get('RAILWAY_VOLUME_MOUNT_PATH')
        if not railway_mount or Path(railway_mount).resolve() != root:
            raise RuntimeError('Attach a Railway volume to this service at /data and set NEXUS_DATA_DIR=/data before deploying.')
    if not root.is_dir() or not is_mounted(root):
        raise RuntimeError('Persistent volume is missing. Mount it at /data before starting; the bot will not use temporary container storage.')
    return root


def prepare_state(root):
    """Initialize once; preserve the stored roster, maps, settings, and database."""
    config_path = root / 'config.local.json'
    if config_path.exists():
        config = json.loads(config_path.read_text(encoding='utf-8'))
    else:
        if any((root / 'data' / name).exists() for name in ('test.sqlite3', 'live.sqlite3')):
            raise RuntimeError('A database exists without its config.local.json. Restore its matching configuration before starting.')
        config = json.loads(SEED_CONFIG.read_text(encoding='utf-8'))
    if not isinstance(config, dict) or config.get('mode') not in {'test', 'live'}:
        raise RuntimeError('Unknown hosted mode.')
    if config['mode'] == 'live':
        validate_live(config, root / 'data' / 'live.sqlite3')
    for child in (config_path, root/'data', root/'backups', root/'review'):
        if not child.resolve().is_relative_to(root):
            raise RuntimeError('Hosted state must stay inside its mounted volume. Check the imported folder paths.')
    config['database_dir'] = str(root / 'data')
    config['backup_dir'] = str(root / 'backups')
    for name in ('data', 'backups', 'review'):
        (root / name).mkdir(exist_ok=True, mode=0o700)
    write_json(config_path, config)
    return config_path, config


async def execute(action, root, environ):
    # The same volume lock covers bootstrap, setup, running, and manual backups.
    # A second replica must never reconcile roles or award activity concurrently.
    with instance_lock(root / '.nexus.lock'):
        config_path, config = prepare_state(root)
        if config['mode'] == 'test' and (Path(config['database_dir']) / 'live.sqlite3').exists() and action != 'activate':
            raise RuntimeError('Live migration exists. Resume activation before other hosted actions.')
        if action in {'plan', 'configure'} and config['mode'] == 'live':
            raise RuntimeError('Test server configuration is disabled after live activation.')
        if action == 'backup':
            database = Path(config['database_dir']) / (config['mode'] + '.sqlite3')
            if not database.exists():
                raise RuntimeError(f"No {config['mode']} database exists yet. No empty database was created.")
            store = Store(database)
            try:
                print('Backup saved: '+str(store.backup(config['backup_dir'])), flush=True)
            finally:
                store.close()
            return
        token = environ.get('NEXUS_TOKEN', '').strip()
        if not token:
            raise RuntimeError('Set NEXUS_TOKEN in the hosting service Variables. There is no terminal token prompt in hosted mode.')
        if action in {'plan', 'configure'}:
            confirmation = environ.get('NEXUS_SETUP_CONFIRMATION', '')
            if action == 'configure' and confirmation != SETUP_CONFIRMATION:
                raise RuntimeError('For the reviewed setup, set NEXUS_SETUP_CONFIRMATION to CONFIGURE PRIVATE TEST SERVER. Use NEXUS_ACTION=plan for a preview.')
            applied = await configure(config_path, config, token, confirmation=confirmation,
                                      plan_only=action == 'plan', output_dir=root/'review')
            if action == 'configure':
                if not applied:
                    raise RuntimeError('Configuration was not applied. Keep the volume and review the setup log.')
                print('Cloud configuration finished. Remove the listed temporary Discord permissions, '
                      'set NEXUS_ACTION=run, remove NEXUS_SETUP_CONFIRMATION, and redeploy this same service.', flush=True)
            return
        if not config.get('role_ids') or not config.get('channel_ids'):
            raise RuntimeError('Server configuration is not finished. Set NEXUS_ACTION=plan to check permissions, '
                               'then use NEXUS_ACTION=configure for the reviewed setup on this same volume.')
        if action == 'activate':
            config = activate(config_path, config, environ.get('NEXUS_LAUNCH_CONFIRMATION', ''))
        print('Starting Galactic Nexus hosted worker in '+config['mode'].upper()+' MODE.', flush=True)
        await run_bot(config, token)
        # A safety shutdown or worker failure must be visible to the supervisor.
        # Intentional host shutdown cancels this task and follows graceful_shutdown.
        raise RuntimeError('The bot stopped. Check the preceding Discord/permission log before restarting.')


async def graceful_shutdown(operation):
    loop = asyncio.get_running_loop()
    task = asyncio.current_task()
    installed = []
    for signum in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(signum, task.cancel)
            installed.append(signum)
        except (NotImplementedError, RuntimeError):
            pass
    try:
        await operation
    except asyncio.CancelledError:
        print('Hosted worker stopped cleanly. Saved state remains on the volume.', flush=True)
    finally:
        for signum in installed:
            loop.remove_signal_handler(signum)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', nargs='?', choices=('run', 'plan', 'configure', 'backup', 'activate'),
                        default=os.environ.get('NEXUS_ACTION', 'run'))
    args = parser.parse_args(argv)
    if args.action not in {'run', 'plan', 'configure', 'backup', 'activate'}:
        parser.error('NEXUS_ACTION must be run, plan, configure, backup, or activate.')
    os.umask(0o077)
    try:
        root = mounted_data_dir(os.environ)
        asyncio.run(graceful_shutdown(execute(args.action, root, os.environ)))
    except (RuntimeError, ValueError, OSError, discord.DiscordException) as exc:
        print('Hosted worker stopped: '+str(exc), file=sys.stderr, flush=True)
        return 1
    except KeyboardInterrupt:
        print('Hosted worker stopped.', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
