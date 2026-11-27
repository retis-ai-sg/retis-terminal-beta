"""Assets: files of known types kept in prompits pools for the one agent that owns the store.

The store keeps each asset's metadata as a row in a table pool and its bytes as a blob (`Pool.put_blob`), in the same
pool or a second one. It checks types, sizes, quotas and expiry, and answers who may read or change an asset from a
`Principal` the calling agent has already verified (for a Plaza agent: Plaza's own decision about the caller). It
never authenticates anyone itself and has no HTTP or Plaza code, so any agent can use it.

Owners: `agent` (a calling agent), `user` (a signed-in user, on that user's own call), `site` (the store owner's
own agents), `local` (the one owner of a store on the user's own computer).
Visibility: `private` (the owner), `owner` (agents of the same verified owner account), `site` (any verified caller).

Bytes arrive in parts of PART_BYTES (the last one shorter) so each part fits a JSON request and a Terminal view value.
An upload is checked against its declared size and sha256 when its last part arrives; until then nothing is visible.
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import re
import secrets
import shutil
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterator, List, Mapping, Optional, Tuple

from prompits.core.pool import Pool
from prompits.core.schema import TableSchema

ASSETS = 'assets'
UPLOADS = 'asset_uploads'
PART_BYTES = 192 * 1024
LIST_LIMIT = 50
MiB = 1024 * 1024

OWNER_KINDS = ('agent', 'user', 'site', 'local')
VISIBILITIES = ('private', 'owner', 'site')


def _text(data: bytes) -> bool:
    """UTF-8 text without NUL; a multi-byte character cut at the end of the sample is allowed."""
    if b'\x00' in data:
        return False
    for cut in range(4):
        try:
            data[:len(data) - cut].decode('utf-8')
            return True
        except UnicodeDecodeError:
            continue
    return False


def _json_text(data: bytes) -> bool:
    return _text(data) and data.lstrip(b'\xef\xbb\xbf \t\r\n')[:1] in (b'{', b'[')


# The first bytes each media type must start with; a caller can't store an executable as a picture.
SIGNATURES: Dict[str, Callable[[bytes], bool]] = {
    'image/png': lambda d: d.startswith(b'\x89PNG\r\n\x1a\n'),
    'image/jpeg': lambda d: d.startswith(b'\xff\xd8\xff'),
    'image/webp': lambda d: d[:4] == b'RIFF' and d[8:12] == b'WEBP',
    'image/gif': lambda d: d[:6] in (b'GIF87a', b'GIF89a'),
    'audio/mpeg': lambda d: d.startswith(b'ID3') or d[:2] in (b'\xff\xfb', b'\xff\xf3', b'\xff\xf2'),
    'audio/wav': lambda d: d[:4] == b'RIFF' and d[8:12] == b'WAVE',
    'audio/ogg': lambda d: d.startswith(b'OggS'),
    'audio/webm': lambda d: d.startswith(b'\x1a\x45\xdf\xa3'),
    'audio/mp4': lambda d: d[4:8] == b'ftyp',
    'video/mp4': lambda d: d[4:8] == b'ftyp',
    'video/webm': lambda d: d.startswith(b'\x1a\x45\xdf\xa3'),
    'application/pdf': lambda d: d.startswith(b'%PDF-'),
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document': lambda d: d.startswith(b'PK\x03\x04'),
    'application/vnd.openxmlformats-officedocument.presentationml.presentation': lambda d: d.startswith(b'PK\x03\x04'),
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': lambda d: d.startswith(b'PK\x03\x04'),
    'text/markdown': _text,
    'text/plain': _text,
    'text/csv': _text,
    'application/json': _json_text,
    'application/geo+json': _json_text,
    'application/vnd.apache.parquet': lambda d: d.startswith(b'PAR1'),
    'application/zip': lambda d: d.startswith(b'PK\x03\x04'),
    'application/gzip': lambda d: d.startswith(b'\x1f\x8b'),
}

# Asset types: the media types each may hold and the largest single asset by default. No SVG or HTML: both can run
# script where they are shown.
TYPES: Dict[str, Dict[str, Any]] = {
    'image': {'media': ('image/png', 'image/jpeg', 'image/webp', 'image/gif'), 'max_bytes': 10 * MiB},
    'audio': {'media': ('audio/mpeg', 'audio/wav', 'audio/ogg', 'audio/webm', 'audio/mp4'), 'max_bytes': 50 * MiB},
    'video': {'media': ('video/mp4', 'video/webm'), 'max_bytes': 500 * MiB},
    'document': {'media': ('application/pdf', 'text/markdown', 'text/plain',
                           'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                           'application/vnd.openxmlformats-officedocument.presentationml.presentation',
                           'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'), 'max_bytes': 50 * MiB},
    'data': {'media': ('application/json', 'text/csv', 'application/geo+json', 'application/vnd.apache.parquet'),
             'max_bytes': 100 * MiB},
    'archive': {'media': ('application/zip', 'application/gzip'), 'max_bytes': 200 * MiB},
}

# Per owner kind: (bytes, assets). A store's configuration may change any of these.
DEFAULT_QUOTAS = {'user': (200 * MiB, 1000), 'agent': (1024 * MiB, 10000), 'site': (10 * 1024 * MiB, 50000),
                  'local': (20 * 1024 * MiB, 100000)}

DETAILS = ('name', 'description', 'tags', 'labels', 'visibility', 'expires_at', 'source_ref')
TAG = re.compile(r'^[\w .:-]{1,40}$')
LANGUAGE = re.compile(r'^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8}){0,2}$')
ASSET_ID = re.compile(r'^a-[0-9a-f]{24}$')
UPLOAD_ID = re.compile(r'^u-[0-9a-f]{24}$')
SHA256 = re.compile(r'^[0-9a-f]{64}$')


class AssetError(Exception):
    """A refused request; `status` is the HTTP status an agent should answer with."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass(frozen=True)
class Owner:
    kind: str
    id: str

    @property
    def key(self) -> str:
        return f'{self.kind}:{self.id}'

    @property
    def namespace(self) -> str:
        """The blob folder for this owner: a digest, so no owner id appears in a path."""
        return hashlib.sha256(self.key.encode()).hexdigest()[:32]


@dataclass(frozen=True)
class Principal:
    """Who is calling, as the agent verified it (never as the request says).

    agent_id: the verified calling agent. user_id: the verified user the call is for. account: the verified owner
    account of the calling agent (or the user's own id). site_owner: the call belongs to the store's own owner.
    local: the caller is this computer (a store on the user's own computer, which has one owner).
    """
    agent_id: str = ''
    user_id: str = ''
    account: str = ''
    site_owner: bool = False
    local: bool = False

    @property
    def verified(self) -> bool:
        return bool(self.agent_id or self.user_id or self.site_owner or self.local)


@dataclass(frozen=True)
class Limits:
    quotas: Mapping[str, Tuple[int, int]]
    type_max: Mapping[str, int]
    max_total_bytes: int = 4 * 1024 * MiB
    min_free_bytes: int = 2 * 1024 * MiB
    upload_seconds: int = 1800
    uploads_per_owner: int = 4

    @classmethod
    def from_config(cls, config: Optional[Mapping[str, Any]] = None) -> 'Limits':
        """Limits from a store's configuration: `quotas` {kind: {bytes, assets}}, `type_max_bytes` {type: bytes},
        `max_total_bytes`, `min_free_bytes`, `upload_seconds`, `uploads_per_owner`."""
        config = dict(config or {})
        quotas = dict(DEFAULT_QUOTAS)
        for kind, value in dict(config.get('quotas') or {}).items():
            if kind not in OWNER_KINDS or not isinstance(value, Mapping):
                raise ValueError(f'Unknown quota owner kind: {kind}')
            quotas[kind] = (_whole(value.get('bytes', quotas[kind][0]), 'quota bytes'),
                            _whole(value.get('assets', quotas[kind][1]), 'quota assets'))
        type_max = {name: spec['max_bytes'] for name, spec in TYPES.items()}
        for name, value in dict(config.get('type_max_bytes') or {}).items():
            if name not in TYPES:
                raise ValueError(f'Unknown asset type: {name}')
            type_max[name] = _whole(value, 'type size')
        return cls(quotas=quotas, type_max=type_max,
                   max_total_bytes=_whole(config.get('max_total_bytes', cls.max_total_bytes), 'max_total_bytes'),
                   min_free_bytes=_whole(config.get('min_free_bytes', cls.min_free_bytes), 'min_free_bytes'),
                   upload_seconds=max(60, _whole(config.get('upload_seconds', cls.upload_seconds), 'upload_seconds')),
                   uploads_per_owner=max(1, _whole(config.get('uploads_per_owner', cls.uploads_per_owner),
                                                   'uploads_per_owner')))


def _whole(value: Any, field: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f'{field} must be a whole number.')
    return value


def _iso(seconds: float) -> str:
    return datetime.fromtimestamp(seconds, timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def _table(name: str) -> TableSchema:
    columns = {key: {'type': 'string'} for key in ('id', 'owner_key', 'visibility', 'status', 'asset_type', 'record')}
    return TableSchema({'name': name, 'description': f'Asset store {name}.', 'primary_key': ['id'],
                        'rowSchema': columns})


def _short_text(value: Any, field: str, limit: int, *, required: bool = False) -> str:
    if value is None and not required:
        return ''
    if not isinstance(value, str) or len(value) > limit or any(ord(c) < 32 for c in value):
        raise AssetError(422, f'Invalid {field}.')
    value = value.strip()
    if required and not value:
        raise AssetError(422, f'Provide a {field}.')
    return value


def _tags(value: Any) -> List[str]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 20 or not all(isinstance(t, str) and TAG.fullmatch(t) for t in value):
        raise AssetError(422, 'Tags are up to 20 short words.')
    return sorted(set(value))


def _labels(value: Any) -> Dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, Mapping) or len(value) > 8:
        raise AssetError(422, 'Labels are up to 8 titles by language.')
    labels = {}
    for language, title in value.items():
        if not isinstance(language, str) or not LANGUAGE.fullmatch(language):
            raise AssetError(422, 'Invalid label language.')
        labels[language] = _short_text(title, 'label', 200, required=True)
    return labels


class AssetStore:
    """Asset metadata in `meta_pool`'s tables and bytes in `blob_pool` (default: the same pool)."""

    def __init__(self, meta_pool: Pool, blob_pool: Optional[Pool] = None, *, limits: Optional[Limits] = None,
                 clock: Callable[[], float] = time.time):
        self.meta = meta_pool
        self.blobs = blob_pool or meta_pool
        if not self.blobs.supports_blobs():
            raise ValueError(f'{self.blobs.__class__.__name__} does not store blobs.')
        self.limits = limits or Limits.from_config()
        self.clock = clock
        self.lock = threading.RLock()
        for name in (ASSETS, UPLOADS):
            if not self.meta._TableExists(name):
                self.meta._CreateTable(name, _table(name))

    # ---- rows ------------------------------------------------------------------------------------------------

    def _rows(self, table: str, where: Any = None) -> List[Dict[str, Any]]:
        """Decoded records; `where` is a row id (one row read) or an equality filter."""
        records = []
        for row in self.meta._GetTableData(table, where or None) or []:
            record = row.get('record')
            if isinstance(record, str):  # SQLitePool hands JSON text back already decoded; FileSystemPool does not
                try:
                    record = json.loads(record)
                except ValueError:
                    record = None
            if isinstance(record, dict):
                records.append(record)
        return records

    def _save(self, table: str, record: Dict[str, Any]) -> None:
        row = {'id': record['id'], 'owner_key': record['owner_key'], 'visibility': record.get('visibility', ''),
               'status': record.get('status', ''), 'asset_type': record.get('asset_type', ''),
               'record': json.dumps(record, sort_keys=True, separators=(',', ':'))}
        if not self.meta._Insert(table, row):
            raise AssetError(503, 'The asset store could not save its records.')

    def record(self, asset_id: Any) -> Optional[Dict[str, Any]]:
        """The stored record of an asset, without any access check."""
        if not isinstance(asset_id, str) or not ASSET_ID.fullmatch(asset_id):
            return None
        rows = self._rows(ASSETS, asset_id)
        return rows[0] if rows else None

    def _upload(self, upload_id: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(upload_id, str) or not UPLOAD_ID.fullmatch(upload_id):
            return None
        rows = self._rows(UPLOADS, upload_id)
        return rows[0] if rows else None

    @staticmethod
    def _blob_key(record: Mapping[str, Any]) -> str:
        return f"assets/{record['owner_ns']}/{record['sha256']}"

    # ---- access ----------------------------------------------------------------------------------------------

    @staticmethod
    def owner_for(principal: Principal, kind: str) -> Owner:
        """The owner a new asset of `kind` gets for this caller; refused when the caller can't own that kind."""
        if principal.local:
            return Owner('local', 'local')
        if kind == 'agent' and principal.agent_id:
            return Owner('agent', principal.agent_id)
        if kind == 'user' and principal.user_id:
            return Owner('user', principal.user_id)
        if kind == 'site' and principal.site_owner:
            return Owner('site', 'site')
        raise AssetError(403, f'This caller cannot keep {kind} assets.')

    @staticmethod
    def is_owner(record: Mapping[str, Any], principal: Principal) -> bool:
        kind, owner_id = record['owner']['kind'], record['owner']['id']
        return ((kind == 'agent' and bool(principal.agent_id) and principal.agent_id == owner_id)
                or (kind == 'user' and bool(principal.user_id) and principal.user_id == owner_id)
                or (kind == 'site' and principal.site_owner)
                or (kind == 'local' and principal.local))

    def may_read(self, record: Mapping[str, Any], principal: Principal) -> bool:
        if self.is_owner(record, principal):
            return True
        visibility = record.get('visibility')
        if visibility == 'site':
            return principal.verified
        if visibility == 'owner':
            return bool(record.get('account')) and record.get('account') == principal.account
        return False

    def may_change(self, record: Mapping[str, Any], principal: Principal) -> bool:
        return self.is_owner(record, principal)

    def may_delete(self, record: Mapping[str, Any], principal: Principal) -> bool:
        """The owner, or the store's own owner (to take anything down)."""
        return self.is_owner(record, principal) or principal.site_owner

    def readable(self, asset_id: Any, principal: Principal) -> Dict[str, Any]:
        """The record when this caller may read it; one answer (404) whether it is missing or not theirs."""
        record = self.record(asset_id)
        if not record or record.get('status') != 'ready' or self._expired(record) or not self.may_read(record, principal):
            raise AssetError(404, 'No such asset.')
        return record

    def _expired(self, record: Mapping[str, Any]) -> bool:
        expires = record.get('expires_at')
        return isinstance(expires, (int, float)) and expires <= self.clock()

    # ---- checks ----------------------------------------------------------------------------------------------

    def _check_fields(self, fields: Mapping[str, Any], *, local: bool) -> Dict[str, Any]:
        asset_type = fields.get('asset_type')
        if asset_type not in TYPES:
            raise AssetError(422, 'Choose an asset type: ' + ', '.join(TYPES) + '.')
        media_type = fields.get('media_type')
        if media_type not in TYPES[asset_type]['media']:
            raise AssetError(422, f'A {asset_type} asset is one of: ' + ', '.join(TYPES[asset_type]['media']) + '.')
        size = fields.get('size')
        if type(size) is not int or not 1 <= size <= self.limits.type_max[asset_type]:
            raise AssetError(413 if type(size) is int and size > 0 else 422,
                             f'A {asset_type} asset is 1 to {self.limits.type_max[asset_type]} bytes.')
        digest = fields.get('sha256')
        if not isinstance(digest, str) or not SHA256.fullmatch(digest):
            raise AssetError(422, 'Provide the sha256 of the whole file in lowercase hex.')
        return {'asset_type': asset_type, 'media_type': media_type, 'size': size, 'sha256': digest,
                **self._check_details(fields, local=local, creating=True)}

    def _check_details(self, fields: Mapping[str, Any], *, local: bool, creating: bool) -> Dict[str, Any]:
        details: Dict[str, Any] = {}
        if creating or 'name' in fields:
            details['name'] = _short_text(fields.get('name'), 'name', 200, required=True)
        if creating or 'description' in fields:
            details['description'] = _short_text(fields.get('description'), 'description', 1000)
        if creating or 'tags' in fields:
            details['tags'] = _tags(fields.get('tags'))
        if creating or 'labels' in fields:
            details['labels'] = _labels(fields.get('labels'))
        if creating or 'source_ref' in fields:
            details['source_ref'] = _short_text(fields.get('source_ref'), 'source reference', 200)
        if creating or 'visibility' in fields:
            visibility = fields.get('visibility', 'private') or 'private'
            if visibility not in VISIBILITIES or (local and visibility != 'private'):
                raise AssetError(422, 'Visibility is private' + ('' if local else ', owner or site') + '.')
            details['visibility'] = visibility
        if creating or 'expires_at' in fields:
            expires = fields.get('expires_at')
            if expires is not None and (type(expires) is not int or not self.clock() < expires
                                        <= self.clock() + 3650 * 86400):
                raise AssetError(422, 'expires_at is a time in the next ten years, in whole seconds.')
            details['expires_at'] = expires
        return details

    def _disk_free(self) -> Optional[int]:
        place = getattr(self.blobs, 'root_path', None) or os.path.dirname(os.path.abspath(
            str(getattr(self.blobs, 'db_path', '') or ''))) or None
        if not place or not os.path.isdir(place):
            return None
        return shutil.disk_usage(place).free

    def usage(self, owner: Owner) -> Dict[str, int]:
        """What `owner` keeps now, open uploads included, and its quota."""
        records = [r for r in self._rows(ASSETS, {'owner_key': owner.key}) if r.get('status') == 'ready']
        uploads = [u for u in self._rows(UPLOADS, {'owner_key': owner.key}) if u.get('expires', 0) > self.clock()]
        quota_bytes, quota_assets = self.limits.quotas[owner.kind]
        return {'bytes': sum(r['size'] for r in records) + sum(u['size'] for u in uploads),
                'assets': len(records), 'uploads': len(uploads),
                'quota_bytes': quota_bytes, 'quota_assets': quota_assets}

    def _check_room(self, owner: Owner, size: int, replacing: Optional[Mapping[str, Any]]) -> None:
        used = self.usage(owner)
        freed = replacing['size'] if replacing else 0
        if used['uploads'] >= self.limits.uploads_per_owner:
            raise AssetError(429, 'Finish or wait out your other uploads first.')
        if used['bytes'] - freed + size > used['quota_bytes'] or (not replacing and used['assets'] >= used['quota_assets']):
            raise AssetError(507, 'This would go over your storage quota.')
        total = sum(r['size'] for r in self._rows(ASSETS) if r.get('status') == 'ready')
        total += sum(u['size'] for u in self._rows(UPLOADS) if u.get('expires', 0) > self.clock())
        if total - freed + size > self.limits.max_total_bytes:
            raise AssetError(507, 'The asset store is full.')
        free = self._disk_free()
        if free is not None and free - size < self.limits.min_free_bytes:
            raise AssetError(507, 'The disk is too full to keep this asset.')

    # ---- writing ---------------------------------------------------------------------------------------------

    def begin(self, principal: Principal, fields: Mapping[str, Any]) -> Dict[str, Any]:
        """Start an upload: `fields` has asset_type, media_type, size, sha256, name and optional description, tags,
        labels, visibility, expires_at, source_ref, owner ('agent', 'user' or 'site') and replace (an asset id).
        Returns {upload_id, part_bytes, parts, expires_at}."""
        with self.lock:
            replacing = None
            if fields.get('replace') is not None:
                replacing = self.record(fields.get('replace'))
                if not replacing or replacing.get('status') != 'ready' or not self.may_change(replacing, principal):
                    raise AssetError(404, 'No such asset.')
                owner = Owner(**replacing['owner'])
                # A new file for the same asset keeps its name, labels and sharing unless the call changes them.
                fields = {**{k: replacing.get(k) for k in DETAILS}, **fields}
            else:
                owner = self.owner_for(principal, str(fields.get('owner') or 'agent'))
            checked = self._check_fields(fields, local=principal.local)
            if checked['visibility'] == 'owner' and not principal.account:
                raise AssetError(503, 'Your owner account could not be confirmed; choose private or site.')
            self._check_room(owner, checked['size'], replacing)
            now = self.clock()
            upload = {
                'id': 'u-' + secrets.token_hex(12), 'owner_key': owner.key,
                'owner': {'kind': owner.kind, 'id': owner.id}, 'owner_ns': owner.namespace,
                'writer_agent_id': principal.agent_id, 'account': principal.account if owner.kind != 'user' else owner.id,
                'replace': replacing['id'] if replacing else None, 'received': [],
                'parts': max(1, math.ceil(checked['size'] / PART_BYTES)), 'created': now,
                'expires': now + self.limits.upload_seconds, **checked,
            }
            self._save(UPLOADS, upload)
            return {'upload_id': upload['id'], 'part_bytes': PART_BYTES, 'parts': upload['parts'],
                    'expires_at': _iso(upload['expires'])}

    def put_part(self, principal: Principal, upload_id: Any, index: Any, data: bytes) -> Dict[str, Any]:
        """Store one part. The last missing part checks the whole file and makes the asset ready."""
        with self.lock:
            upload = self._upload(upload_id)
            if not upload or upload['expires'] <= self.clock() or not self._same_writer(upload, principal):
                raise AssetError(404, 'No such upload.')
            if type(index) is not int or not 0 <= index < upload['parts']:
                raise AssetError(422, 'Invalid part number.')
            expected = PART_BYTES if index < upload['parts'] - 1 else upload['size'] - PART_BYTES * (upload['parts'] - 1)
            if len(data) != expected:
                raise AssetError(422, f'Part {index} must be {expected} bytes.')
            if index == 0 and not SIGNATURES[upload['media_type']](data[:65536]):
                self._drop_upload(upload)
                raise AssetError(415, f"The file is not {upload['media_type']}.")
            self.blobs.put_blob(f"uploads/{upload['id']}/{index:05d}", [data])
            upload['received'] = sorted(set(upload['received']) | {index})
            if len(upload['received']) < upload['parts']:
                self._save(UPLOADS, upload)
                return {'upload_id': upload['id'], 'received': len(upload['received']), 'parts': upload['parts']}
            return {'upload_id': upload['id'], 'received': upload['parts'], 'parts': upload['parts'],
                    'asset': self._finish(upload)}

    def put(self, principal: Principal, fields: Mapping[str, Any], data: bytes) -> Dict[str, Any]:
        """Keep a whole file in one call (any size the parts allow); returns the asset record."""
        fields = {**fields, 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
        started = self.begin(principal, fields)
        result: Dict[str, Any] = {}
        for index in range(started['parts']):
            result = self.put_part(principal, started['upload_id'], index, data[index * PART_BYTES:(index + 1) * PART_BYTES])
        return result['asset']

    @staticmethod
    def _same_writer(upload: Mapping[str, Any], principal: Principal) -> bool:
        owner = upload['owner']
        if owner['kind'] == 'local':
            return principal.local
        if owner['kind'] == 'user':
            return principal.user_id == owner['id']
        return bool(principal.agent_id) and principal.agent_id == upload['writer_agent_id'] or (
            owner['kind'] == 'site' and principal.site_owner)

    def _parts(self, upload: Mapping[str, Any]) -> Iterator[bytes]:
        for index in range(upload['parts']):
            part = self.blobs.read_blob(f"uploads/{upload['id']}/{index:05d}")
            if part is None:
                raise AssetError(409, 'A part of the upload is missing; start again.')
            yield part

    def _drop_upload(self, upload: Mapping[str, Any]) -> None:
        for key in self.blobs.list_blobs(f"uploads/{upload['id']}/"):
            self.blobs.delete_blob(key)
        self.meta.delete_row(UPLOADS, upload['id'])

    def _finish(self, upload: Dict[str, Any]) -> Dict[str, Any]:
        digest, size = hashlib.sha256(), 0
        for part in self._parts(upload):
            digest.update(part)
            size += len(part)
        if size != upload['size'] or digest.hexdigest() != upload['sha256']:
            self._drop_upload(upload)
            raise AssetError(422, 'The file does not match its size and sha256; start again.')
        key = f"assets/{upload['owner_ns']}/{upload['sha256']}"
        if self.blobs.blob_size(key) != size:
            self.blobs.put_blob(key, self._parts(upload))
        now = self.clock()
        old = self.record(upload['replace']) if upload.get('replace') else None
        record = {
            'id': old['id'] if old else 'a-' + secrets.token_hex(12),
            'revision': old['revision'] + 1 if old else 1,
            'created_at': old['created_at'] if old else now, 'updated_at': now, 'status': 'ready',
            **{k: upload[k] for k in ('owner_key', 'owner', 'owner_ns', 'writer_agent_id', 'account', 'asset_type',
                                      'media_type', 'size', 'sha256', 'name', 'description', 'tags', 'labels',
                                      'source_ref', 'visibility', 'expires_at')},
        }
        self._save(ASSETS, record)
        self._drop_upload(upload)
        if old and old['sha256'] != record['sha256']:
            self._release_blob(old)
        return record

    def _release_blob(self, record: Mapping[str, Any]) -> None:
        """Remove a record's bytes unless another asset of the same owner holds the same file."""
        others = [r for r in self._rows(ASSETS, {'owner_key': record['owner_key']})
                  if r['id'] != record['id'] and r.get('sha256') == record['sha256']]
        if not others:
            self.blobs.delete_blob(self._blob_key(record))

    def update(self, principal: Principal, asset_id: Any, changes: Mapping[str, Any]) -> Dict[str, Any]:
        """Change name, description, tags, labels, visibility, expires_at or source_ref."""
        allowed = set(DETAILS)
        if not changes or set(changes) - allowed:
            raise AssetError(422, 'Change only: ' + ', '.join(sorted(allowed)) + '.')
        with self.lock:
            record = self.readable(asset_id, principal)
            if not self.may_change(record, principal):
                raise AssetError(403, 'Only the owner changes an asset.')
            details = self._check_details(changes, local=principal.local, creating=False)
            if details.get('visibility') == 'owner' and not record.get('account'):
                raise AssetError(422, "This asset's owner account is unknown; choose private or site.")
            record.update(details, updated_at=self.clock())
            self._save(ASSETS, record)
            return record

    def delete(self, principal: Principal, asset_id: Any) -> bool:
        """Remove an asset and, when nothing else holds them, its bytes. Nothing of it is kept."""
        with self.lock:
            record = self.record(asset_id)
            if not record or not self.may_delete(record, principal):
                raise AssetError(404, 'No such asset.')
            self.meta.delete_row(ASSETS, record['id'])
            self._release_blob(record)
            return True

    # ---- reading ---------------------------------------------------------------------------------------------

    def read(self, principal: Principal, asset_id: Any, offset: Any = 0, length: Any = PART_BYTES) -> Tuple[Dict[str, Any], bytes]:
        """The record and up to `length` (≤ PART_BYTES) bytes from `offset`."""
        if type(offset) is not int or offset < 0 or type(length) is not int or not 0 < length <= PART_BYTES:
            raise AssetError(422, f'Read 1 to {PART_BYTES} bytes from a non-negative offset.')
        record = self.readable(asset_id, principal)
        if offset > record['size']:
            raise AssetError(416, 'The offset is past the end of the asset.')
        data = self.blobs.read_blob(self._blob_key(record), offset, length)
        if data is None:
            raise AssetError(503, "The asset's bytes are unavailable.")
        return record, data

    def list(self, principal: Principal, *, scope: str, owner: str = 'agent', asset_type: Optional[str] = None,
             tag: Optional[str] = None, name: Optional[str] = None, limit: int = 20, cursor: Optional[str] = None
             ) -> Dict[str, Any]:
        """Assets in `scope`: 'mine' (what this caller owns as `owner`) or 'site' (shared with the whole site), at
        most LIST_LIMIT at a time, newest first."""
        if type(limit) is not int or not 1 <= limit <= LIST_LIMIT:
            raise AssetError(422, f'List 1 to {LIST_LIMIT} assets at a time.')
        if asset_type is not None and asset_type not in TYPES:
            raise AssetError(422, 'Unknown asset type.')
        if tag is not None and (not isinstance(tag, str) or not TAG.fullmatch(tag)):
            raise AssetError(422, 'Invalid tag.')
        name = _short_text(name, 'name filter', 200).lower() if name is not None else ''
        try:
            start = int(cursor or 0)
        except (TypeError, ValueError):
            raise AssetError(422, 'Invalid cursor.') from None
        if scope == 'mine':
            rows = self._rows(ASSETS, {'owner_key': self.owner_for(principal, owner).key})
        elif scope == 'site' and principal.verified and not principal.local:
            rows = self._rows(ASSETS, {'visibility': 'site'})
        else:
            raise AssetError(422, "Scope is 'mine'" + ("" if principal.local else " or 'site'") + '.')
        rows = [r for r in rows if r.get('status') == 'ready' and not self._expired(r) and self.may_read(r, principal)
                and (asset_type is None or r['asset_type'] == asset_type) and (tag is None or tag in r['tags'])
                and (not name or name in r['name'].lower())]
        rows.sort(key=lambda r: (-r['updated_at'], r['id']))
        page = rows[start:start + limit]
        following = start + limit if start + limit < len(rows) else None
        return {'assets': page, 'next_cursor': str(following) if following is not None else None}

    def tagged(self, tag: str, *, asset_type: Optional[str] = None, owner_kind: Optional[str] = None) -> List[Dict[str, Any]]:
        """Every ready, unexpired asset carrying `tag`, of every owner, newest first, without any access check (like
        record()). For the store's own agent when it decides itself who may see each one, as AssetStorage's Phema
        library does with Plaza's lists; a caller is shown only what that decision allows, through public_view."""
        if not isinstance(tag, str) or not TAG.fullmatch(tag):
            raise AssetError(422, 'Invalid tag.')
        rows = [r for r in self._rows(ASSETS, {'asset_type': asset_type} if asset_type else None)
                if r.get('status') == 'ready' and not self._expired(r) and tag in (r.get('tags') or [])
                and (owner_kind is None or r['owner']['kind'] == owner_kind)]
        rows.sort(key=lambda r: (-r['updated_at'], r['id']))
        return rows

    def content(self, record: Mapping[str, Any], limit: int) -> bytes:
        """The whole file of an asset record of at most `limit` bytes, without any access check (see tagged())."""
        if record['size'] > limit:
            raise AssetError(413, f'The asset is larger than {limit} bytes.')
        data = self.blobs.read_blob(self._blob_key(record), 0, record['size'])
        if data is None or len(data) != record['size']:
            raise AssetError(503, "The asset's bytes are unavailable.")
        return data

    # ---- housekeeping ----------------------------------------------------------------------------------------

    def sweep(self) -> Dict[str, int]:
        """Remove expired assets, abandoned uploads and bytes no asset holds any more."""
        removed = {'assets': 0, 'uploads': 0, 'blobs': 0}
        with self.lock:
            now = self.clock()
            for record in self._rows(ASSETS):
                if self._expired(record):
                    self.meta.delete_row(ASSETS, record['id'])
                    self._release_blob(record)
                    removed['assets'] += 1
            open_uploads = set()
            for upload in self._rows(UPLOADS):
                if upload.get('expires', 0) <= now:
                    self._drop_upload(upload)
                    removed['uploads'] += 1
                else:
                    open_uploads.add(upload['id'])
            held = {self._blob_key(r) for r in self._rows(ASSETS)}
            for key in self.blobs.list_blobs('assets/'):
                if key not in held:
                    self.blobs.delete_blob(key)
                    removed['blobs'] += 1
            for key in self.blobs.list_blobs('uploads/'):
                if key.split('/')[1] not in open_uploads:
                    self.blobs.delete_blob(key)
                    removed['blobs'] += 1
        return removed


def public_view(record: Mapping[str, Any], principal: Principal) -> Dict[str, Any]:
    """What a caller sees of an asset: never the owner's id, the account or storage paths."""
    return {
        'asset_id': record['id'], 'asset_type': record['asset_type'], 'media_type': record['media_type'],
        'name': record['name'], 'description': record.get('description', ''), 'tags': list(record.get('tags') or []),
        'labels': dict(record.get('labels') or {}), 'size': record['size'], 'sha256': record['sha256'],
        'revision': record['revision'], 'visibility': record['visibility'], 'owner_kind': record['owner']['kind'],
        'mine': AssetStore.is_owner(record, principal), 'source_ref': record.get('source_ref', ''),
        'created_at': _iso(record['created_at']), 'updated_at': _iso(record['updated_at']),
        'expires_at': _iso(record['expires_at']) if record.get('expires_at') else None,
    }


def encode(data: bytes) -> str:
    return base64.b64encode(data).decode('ascii')


def decode(text: Any, limit: int = PART_BYTES) -> bytes:
    """Base64 text to bytes, at most `limit` of them."""
    if not isinstance(text, str) or len(text) > 4 * math.ceil(limit / 3):
        raise AssetError(413, f'A part is at most {limit} bytes.')
    try:
        return base64.b64decode(text, validate=True)
    except (ValueError, TypeError):
        raise AssetError(422, 'Send the part as base64.') from None
