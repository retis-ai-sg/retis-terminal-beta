#!/usr/bin/env python3
"""Local AssetStorage on this computer: keeps the files its owner chooses to keep, for this computer's Terminal.

It listens on 127.0.0.1 only and is announced by Bonjour; this computer's Terminal uses it at once, with no Plaza,
sign-in, pairing or token (docs/spec/local-resource-connections.md). Every asset has the one local owner and stays
private. Its records and files live in --state, outside the program folder, or in the location chosen in Retis MAS
Manager (a folder such as one on an external drive, settle_location); nothing leaves this computer.

    python3 scripts/run_local_asset_storage.py --state <folder> --port 28540 [--health-port 28541]
"""
import argparse
import asyncio
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from prompits.components.logs import configure_logging  # noqa: E402  every start's log format, set before it serves
NAME = 'Local AssetStorage'
SITE_CONFIG = ROOT / 'phemacast/configs/asset_storage.pulser'
PULSES = ('asset_put', 'asset_put_part', 'asset_get', 'asset_list', 'asset_update', 'asset_delete', 'asset_usage')
# The user's own disk: a larger store than a site's, and it always leaves room for the computer itself.
LIMITS = {'max_total_bytes': 20 * 1024 ** 3, 'min_free_bytes': 2 * 1024 ** 3}
# What it says beside its row in Retis MAS Manager, in English and Traditional Chinese (prompits.components.health
# `reasons`); {0} is a folder.
SAID = {
    'starting': ('Starting', '啟動中'),
    'unavailable': ('The storage location {0} is not available. Connect its drive, or choose another location in Settings.',
                    '儲存位置 {0} 目前無法使用。請連接它所在的磁碟，或在「設定」中選擇其他位置。'),
    'taken': ('{0} already holds AssetStorage files. Move them away, or choose another location in Settings.',
              '{0} 已有 AssetStorage 的檔案。請先將它們移走，或在「設定」中選擇其他位置。'),
    'moving': ('Moving your files to {0}…', '正在將您的檔案移到 {0}…'),
    'full': ('The disk that holds your files is almost full; nothing new can be kept.', '存放您檔案的磁碟快滿了，無法再保存新的檔案。'),
}


class Said(str):
    """A reason in English, as the health answer's `reason`, carrying the same in Traditional Chinese (`reasons`)."""
    reasons: dict


def said(key, *values):
    english, chinese = SAID[key]
    reason = Said(english.format(*values))
    reason.reasons = {'zh-Hant': chinese.format(*values)}
    return reason


def reasons(reason):
    return getattr(reason, 'reasons', None)


def prepare(state, port):
    from phemacast.network.configure import configure, upgrade, write
    state = Path(state).expanduser().resolve()
    if state.is_relative_to(ROOT):
        raise ValueError('Keep runtime state outside the source checkout.')
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = state / 'asset_storage.json'
    if not path.exists():
        configure(path, port=port, name=NAME, kind='pulser', execute=True, pulses=list(PULSES))
    document = json.loads(path.read_text())
    if document['local_network']['port'] != port:
        raise ValueError('Local AssetStorage already uses another port. Stop it before changing its configuration.')
    upgrade(document['local_network'])
    limits = document.setdefault('limits', dict(LIMITS))
    # The limits chosen in Retis MAS Manager (prompits.components.settings), in GB.
    from prompits.components import settings as component_settings
    chosen = component_settings.read(state)
    for key, field in (('max_total_bytes', 'max_total_gb'), ('min_free_bytes', 'min_free_gb')):
        value = chosen.get(field)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
            limits[key] = int(value * 1024 ** 3)
    if isinstance(chosen.get('location'), str):
        document['location'] = chosen['location'].strip()  # the files move there when it starts (settle_location)
    write(path, document)
    return path


# Where the files are kept: the index and the files themselves, in the state folder unless the user chose a location.
STORE_FOLDER = 'Retis AssetStorage'
STORE_ITEMS = ('assets.sqlite', 'assets.sqlite-wal', 'assets.sqlite-shm', 'blobs')
STAGING = '.moving'


def store_root(path, document):
    """The folder that holds the index and the files now."""
    return Path(document.get('store_root') or Path(path).parent)


def _same(one, other):
    return os.path.realpath(one) == os.path.realpath(other)


def _remove(folder):
    for name in STORE_ITEMS:
        item = Path(folder) / name
        if item.is_dir() and not item.is_symlink():
            shutil.rmtree(item)
        elif item.exists() or item.is_symlink():
            item.unlink()


def _finish(old, new):
    """The second half of a move: the copied items take their places, then the old ones go."""
    staging = Path(new) / STAGING
    if staging.is_dir():
        for item in list(staging.iterdir()):
            target = Path(new) / item.name
            if target.is_dir():
                shutil.rmtree(target)
            os.replace(item, target)
        staging.rmdir()
    if not _same(old, new):
        _remove(old)


def unmounted_drive(folder):
    """Whether `folder` sits where drives are mounted (/Volumes, /media, /mnt) while no drive is mounted there: a folder
    left behind by a drive that is not connected, which is on this computer's own disk."""
    folder = Path(os.path.realpath(folder))
    if not folder.parts[1:2] or folder.parts[1] not in ('Volumes', 'media', 'mnt'):
        return False
    place = folder
    while place != place.parent and not os.path.ismount(place):
        place = place.parent
    return place == place.parent  # the nearest mount point is the computer's own disk


def settle_location(path, say=lambda reason: None):
    """Bring the files to the location chosen in Retis MAS Manager: '' once the store can open there, else why not.

    The chosen folder is never created, so a drive that is not connected is said, not replaced by an empty folder on
    this computer's disk. The files are copied into a staging folder first, and the move is recorded before the old copy
    goes, so a move stopped half way finishes at the next start."""
    path = Path(path)
    state = path.parent
    document = json.loads(path.read_text())
    location = (document.get('location') or '').strip()
    if location and (not Path(location).expanduser().is_dir() or unmounted_drive(Path(location).expanduser())):
        return said('unavailable', location)
    current = store_root(path, document)
    if document.get('moved_from'):
        _finish(document['moved_from'], current)
        document.pop('moved_from')
        write_document(path, document)
    wanted = Path(location).expanduser() / STORE_FOLDER if location else state
    if _same(current, wanted):
        return ''
    present = [name for name in STORE_ITEMS if (current / name).exists()]
    if present and any((wanted / name).exists() for name in STORE_ITEMS):
        return said('taken', wanted)
    if present:
        say(said('moving', wanted))
        wanted.mkdir(exist_ok=True)
        staging = wanted / STAGING
        if staging.exists():
            shutil.rmtree(staging)  # a copy stopped half way before the move was recorded
        staging.mkdir()
        for name in present:
            if (current / name).is_dir():
                shutil.copytree(current / name, staging / name)
            else:
                shutil.copy2(current / name, staging / name)
        document.update(store_root=str(wanted) if location else '', moved_from=str(current))
        write_document(path, document)
        _finish(current, wanted)
        document.pop('moved_from')
    else:
        document['store_root'] = str(wanted) if location else ''
    write_document(path, document)
    return ''


def write_document(path, document):
    from phemacast.network.configure import write
    write(path, document)


def pulser_config(path, document):
    """The site pulser's pulses, run in local mode with pools in the state folder."""
    site = json.loads(SITE_CONFIG.read_text())
    state = Path(path).parent
    store = store_root(path, document)  # the index and the files: the chosen location, else the state folder
    return {'name': NAME, 'host': '127.0.0.1', 'port': document['local_network']['port'], 'plaza_url': '',
            'role': 'pulser', 'description': 'Files you keep on this computer.', 'tags': site['tags'],
            'pools': [{'type': 'FileSystemPool', 'name': 'local_asset_storage', 'root_path': str(state / 'agent')}],
            'asset_storage': {'mode': 'local', 'sweep_seconds': 3600, 'limits': document['limits'],
                              'metadata_pool': {'type': 'SQLitePool', 'name': 'asset_metadata',
                                                'db_path': str(store / 'assets.sqlite')},
                              'blob_pool': {'type': 'FileSystemPool', 'name': 'asset_blobs',
                                            'root_path': str(store / 'blobs')}},
            'supported_pulses': copy.deepcopy([p for p in site['supported_pulses'] if p['name'] in PULSES]),
            'local_network': document['local_network']}


def build(path):
    from phemacast.network.pulser import install_pulser_local
    from phemacast.pulsers.asset_storage_pulser import AssetStoragePulser
    document = json.loads(Path(path).read_text())
    pulser = AssetStoragePulser(config=pulser_config(path, document), auto_register=False)
    return pulser, install_pulser_local(pulser)


# Network file systems: their locking does not suit the index (SQLite), so they are not offered.
NETWORK_FILE_SYSTEMS = {'smbfs', 'nfs', 'nfs4', 'afpfs', 'webdav', 'cifs', 'smb3', 'fuse.sshfs', 'sshfs'}


def network_mounts():
    """The folders where a network share is mounted, from the mount table; none when it cannot be read."""
    try:
        listed = subprocess.run(['mount'], capture_output=True, text=True, timeout=2, check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return set()
    found = set()
    for line in listed.splitlines():
        # macOS: "//user@host/share on /Volumes/x (smbfs, ...)"; Linux: "host:/x on /mnt/x type nfs4 (...)"
        if ' on ' not in line:
            continue
        place = line.split(' on ', 1)[1]
        kind = place.split(' type ', 1)[1].split()[0] if ' type ' in place else place.rsplit(' (', 1)[-1].split(',')[0].rstrip(')')
        if kind in NETWORK_FILE_SYSTEMS:
            found.add((place.split(' type ', 1)[0] if ' type ' in place else place.rsplit(' (', 1)[0]).strip())
    return found


def drives():
    """Drives connected to this computer besides its own disk, to offer as the location: macOS /Volumes (its own disk
    is a link there), Linux /media/<user>/<drive> and /mnt, Windows drive letters other than C:. Hidden and system
    entries (Time Machine's), folders where nothing is mounted now and network shares are left out."""
    found, shared = [], network_mounts()
    for base, depth in (('/Volumes', 1), ('/media', 2), ('/mnt', 1)):
        level = [Path(base)] if Path(base).is_dir() else []
        for _ in range(depth):
            level = [item for folder in level for item in sorted(folder.iterdir())
                     if item.is_dir() and not item.is_symlink() and not item.name.startswith(('.', 'com.apple.'))]
        # Only a drive mounted there now: a leftover empty folder in /Volumes would put the files on this computer's disk.
        found += [str(item) for item in level if os.path.ismount(item) and str(item) not in shared]
    if os.name == 'nt':
        found += [f'{letter}:\\' for letter in 'DEFGHIJKLMNOPQRSTUVWXYZ' if Path(f'{letter}:\\').exists()]
    return found[:16]


def health(pulser, path):
    """Ready unless the disk that holds the files is too full to keep anything new. Its details offer the drives
    connected now as the location (prompits.components.health `details`)."""
    from prompits.components.health import health_payload
    try:
        details = {'suggestions': {'location': drives()}}
    except OSError:
        details = {}
    if shutil.disk_usage(store_root(path, json.loads(Path(path).read_text()))).free < pulser.asset_store.limits.min_free_bytes:
        full = said('full')
        return health_payload(ready=False, version='', details=details, reason=full, reasons=reasons(full))
    return health_payload(ready=True, version='', details=details)


async def serve(path, health_port=None, retry_seconds=10):
    """Answer the health check at once; bring the files to their location first (saying so), then serve them. While
    the location is not available, it says so and looks again every `retry_seconds`."""
    from prompits.components.health import health_payload, serve_health
    status = {'reason': said('starting'), 'pulser': None}

    def report():
        return health(status['pulser'], path) if status['pulser'] else \
            health_payload(ready=False, version='', reason=status['reason'], reasons=reasons(status['reason']))
    checker = await serve_health(health_port, report) if health_port else None
    resource = None
    try:
        while problem := await asyncio.to_thread(settle_location, path, lambda words: status.update(reason=words)):
            status['reason'] = problem
            await asyncio.sleep(retry_seconds)
        pulser, resource = build(path)
        await resource.start()
        status['pulser'] = pulser
        await resource.task
    finally:
        if checker:
            checker.close()
        if resource:
            await resource.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--port', type=int, default=28540)
    parser.add_argument('--health-port', type=int, help='Answer the component health check on 127.0.0.1 at this port.')
    args = parser.parse_args()
    configure_logging()  # a time and a level on every record (Retis MAS Manager → Logs, Last error)
    asyncio.run(serve(prepare(args.state, args.port), args.health_port))
