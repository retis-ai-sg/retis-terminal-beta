"""Which saved versions of a Terminal window's workspace stay in its history, and each version's picture.

Every workspace save keeps the version it replaces as a `workspace-revision` record (store.py). Without a limit
those records only grew: one window kept 1,534 versions. After each save the window keeps:

- every minute's last version for the last 10 minutes,
- every hour's last version for the last 24 hours,
- the last version of each of its most recent N ten-minute periods, days, weeks and months that had a save, with N
  chosen in Terminal settings (`workspaceHistory`) per account and Terminal window.

Everything else, and the picture taken of it, is deleted. Days, weeks and months follow this computer's clock.
"""
import time
from datetime import date

from fastapi import HTTPException

REVISION = 'workspace-revision'
SHOT = 'workspace-shot'
TIERS = ('tenMinute', 'daily', 'weekly', 'monthly')
DEFAULTS = {'tenMinute': 6, 'daily': 7, 'weekly': 4, 'monthly': 6}
MOST = 999
# Fixed by the person's request: every minute for the last 10 minutes, every hour for the last 24 hours.
MINUTE_SPAN = 600
HOUR_SPAN = 86_400
SHOT_WIDTH, SHOT_HEIGHT = 640, 400


def validate(value):
    """The four counts a person chose; each a whole number from 0 (keep none) to 999."""
    if not isinstance(value, dict) or set(value) - set(TIERS):
        raise HTTPException(422, 'Workspace history keeps ten-minute, daily, weekly and monthly versions only.')
    for name, count in value.items():
        if type(count) is not int or not 0 <= count <= MOST:
            raise HTTPException(422, 'Each workspace history count must be a whole number from 0 to 999.')
    return {**DEFAULTS, **value}


def policy(store, owner, key):
    """The counts saved for this window (or the account's preferences outside a window), defaults otherwise."""
    record_id = key if key.startswith('window.') else 'preferences'
    try:
        chosen = store.get(owner, 'settings', record_id).get('workspaceHistory')
    except HTTPException:
        chosen = None
    return {**DEFAULTS, **(chosen if isinstance(chosen, dict) else {})}


def _buckets(stamp):
    local = time.localtime(stamp)
    day = (local.tm_year, local.tm_yday)
    return {
        'minute': (*day, local.tm_hour, local.tm_min),
        'hour': (*day, local.tm_hour),
        'tenMinute': (*day, local.tm_hour, local.tm_min // 10),
        'daily': day,
        'weekly': date(local.tm_year, local.tm_mon, local.tm_mday).isocalendar()[:2],
        'monthly': (local.tm_year, local.tm_mon),
    }


def kept(revisions, counts, now=None):
    """The revision numbers to keep from `revisions`, a list of (revision, saved time) pairs.

    Each kept version is the last one saved in its minute, hour, ten-minute period, day, week or month.
    """
    now = time.time() if now is None else now
    ordered = sorted(revisions, key=lambda item: (item[1], item[0]), reverse=True)
    keep, seen = set(), {name: set() for name in ('minute', 'hour', *TIERS)}
    for revision, stamp in ordered:
        age = now - stamp
        for name, bucket in _buckets(stamp).items():
            if bucket in seen[name]:
                continue
            if name == 'minute' and age >= MINUTE_SPAN or name == 'hour' and age >= HOUR_SPAN:
                continue
            if name in TIERS and len(seen[name]) >= counts.get(name, 0):
                continue
            seen[name].add(bucket)
            keep.add(revision)
    return keep


def prune(store, owner, key, now=None):
    """Delete the versions of this window's workspace (and their pictures) that the rules above no longer keep."""
    rows = store.revision_times(owner, REVISION, key)
    keep = kept([(revision, stamp) for _, revision, stamp in rows], policy(store, owner, key), now)
    gone = [record_id for record_id, revision, _ in rows if revision not in keep]
    try:
        current = store.get(owner, 'workspace-state', key)['revision']
    except HTTPException:
        current = None
    pictures = [record_id for record_id, revision, _ in store.revision_times(owner, SHOT, key)
                if revision != current and revision not in keep]
    store.delete_ids(owner, REVISION, gone)
    store.delete_ids(owner, SHOT, pictures)
    return len(gone)


def prune_all(store, now=None):
    """Apply each window's rules to every window, so windows that no longer save also shed old versions."""
    return sum(prune(store, owner, key, now) for owner, key in store.revision_keys(REVISION))


def picture(value):
    """A history picture: a JPEG of at most 640 × 400, re-encoded so no metadata is kept."""
    from .workspace_previews import raster
    image = raster(value)
    if image['width'] > SHOT_WIDTH or image['height'] > SHOT_HEIGHT:
        raise HTTPException(422, 'A workspace history picture is at most 640 × 400.')
    return {'image': image['image'], 'width': image['width'], 'height': image['height']}
