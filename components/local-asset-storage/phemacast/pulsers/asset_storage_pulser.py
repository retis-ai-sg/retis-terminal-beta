"""AssetStorage: a pulser that keeps typed files (pictures, audio, video, documents, data, archives) for other agents
and for users who choose to keep their own files, on prompits pools (`prompits.core.asset_store`).

Two modes, set by `asset_storage.mode` in its configuration:

- `site`: one agent on a site, registered with its Plaza. Who is calling comes only from the identity the agent
  runtime verified with Plaza for this call (`_inject_remote_caller_context_for_practice`); anything a request says
  about its caller is dropped. An agent keeps its own assets; a signed-in user keeps assets only on a call made for
  that user and naming `owner: "user"`; site assets belong to agents of this store's own owner account.
- `local`: a component on the user's own computer (scripts/run_local_asset_storage.py). Only programs on this
  computer reach it (phemacast.network.service), so every asset has the one local owner and stays private.

Pulses: asset_put, asset_put_part, asset_get, asset_list, asset_update, asset_delete, asset_usage. Bytes travel as
base64 parts of at most PART_BYTES, so a part fits one JSON request and one Terminal view value.

In site mode it is also a Phema library (asset_phema_library.py): the Phemas people keep here, listed and opened in
the New Data Browser with Plaza's See / Open / Change parameters lists. `asset_storage.phema_library: false` turns
it off.
"""
from __future__ import annotations

import copy
import hashlib
import threading
import time
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from fastapi import HTTPException

from phemacast.agents.pulser import ConfigInput, Pulser, _read_config
from prompits.core.asset_store import (PART_BYTES, TYPES, AssetError, AssetStore, Limits, Principal, decode, encode,
                                       public_view)

PULSES = ('asset_put', 'asset_put_part', 'asset_get', 'asset_list', 'asset_update', 'asset_delete', 'asset_usage')
DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / 'configs' / 'asset_storage.pulser'
ACCOUNT_SECONDS = 60


def _pool(config: Mapping[str, Any], default_name: str):
    """A blob-capable pool from configuration: FileSystemPool (root_path) or SQLitePool (db_path)."""
    kind = config.get('type')
    name = str(config.get('name') or default_name)
    description = str(config.get('description') or 'AssetStorage pool')
    if kind == 'FileSystemPool' and config.get('root_path'):
        from prompits.pools.filesystem import FileSystemPool
        return FileSystemPool(name, description, str(Path(config['root_path']).expanduser()))
    if kind == 'SQLitePool' and config.get('db_path'):
        from prompits.pools.sqlite import SQLitePool
        return SQLitePool(name, description, str(Path(config['db_path']).expanduser()))
    raise ValueError(f'AssetStorage {default_name} must be a FileSystemPool with root_path or a SQLitePool with db_path.')


class AssetStoragePulser(Pulser):
    """Keeps assets in its own metadata and blob pools; see the module docstring."""

    def __init__(self, config: Optional[ConfigInput] = None, *, store: Optional[AssetStore] = None, **kwargs: Any):
        settings = copy.deepcopy(_read_config(config if config is not None else DEFAULT_CONFIG))
        if isinstance(config, (str, Path)):
            kwargs.setdefault('config_path', config)
        if not settings.get('supported_pulses'):
            defaults = _read_config(DEFAULT_CONFIG)
            settings['supported_pulses'] = copy.deepcopy(defaults['supported_pulses'])
        options = dict(settings.get('asset_storage') or {})
        self.asset_mode = options.get('mode', 'site')
        if self.asset_mode not in ('site', 'local'):
            raise ValueError("asset_storage.mode is 'site' or 'local'.")
        self.asset_store = store or AssetStore(
            _pool(options.get('metadata_pool') or {}, 'metadata_pool'),
            _pool(options['blob_pool'], 'blob_pool') if options.get('blob_pool') else None,
            limits=Limits.from_config(options.get('limits')))
        self._asset_marker = object()
        self._accounts: Dict[str, tuple] = {}
        self._accounts_lock = threading.Lock()
        self.phema_library = None
        for key in ('name', 'host', 'port', 'plaza_url'):
            if key in settings and key not in kwargs:
                kwargs[key] = settings[key]
        # Register only once the card says what this store keeps: Pulser registers inside __init__, and Plaza
        # keeps the card it was sent until the next registration.
        register = kwargs.pop('auto_register', True)
        super().__init__(config=settings, auto_register=False, **kwargs)
        self._advertise_asset_storage()
        if self.asset_mode == 'site' and options.get('phema_library', True) is not False:
            self._install_phema_library(options)
        self._sweep_stop = threading.Event()
        sweep_seconds = options.get('sweep_seconds', 3600)
        if sweep_seconds:
            threading.Thread(target=self._sweep_loop, args=(int(sweep_seconds),), daemon=True,
                             name='asset-storage-sweep').start()
        if self.plaza_url and register:
            self.register()

    def _advertise_asset_storage(self) -> None:
        """Put the store's mode, part size and types in the card's meta."""
        meta = self.agent_card.setdefault('meta', {})
        meta['asset_storage'] = {
            'mode': self.asset_mode, 'part_bytes': PART_BYTES,
            'types': {name: {'media_types': list(spec['media']), 'max_bytes': self.asset_store.limits.type_max[name]}
                      for name, spec in TYPES.items()},
        }

    def apply_pulser_config(self, config_data, *args: Any, **kwargs: Any) -> None:
        """A configuration reload (Pulser.register runs one) keeps the asset_storage block and the Phema library in
        the card."""
        super().apply_pulser_config(config_data, *args, **kwargs)
        if getattr(self, 'asset_store', None) is not None:
            self._advertise_asset_storage()
        if getattr(self, 'phema_library', None) is not None:
            self.phema_library.advertise()

    # ---- the Phema library (site mode) -----------------------------------------------------------------------

    def _install_phema_library(self, options: Mapping[str, Any]) -> None:
        from phemacast.pulsers.asset_phema_library import AssetPhemaLibrary, state_dir
        place = state_dir(options)
        if place is None:
            self.logger.warning('AssetStorage keeps no Phema library: name asset_storage.library_state_dir.')
            return
        self.phema_library = AssetPhemaLibrary(self, place)
        # A saved Plaza identity names the library's contracts before the first registration; a new one after it.
        self._load_plaza_credentials_from_pool()
        self.phema_library.ensure()

    def register(self, **kwargs: Any):
        """Plaza keeps the card a registration sends. A first registration gives this agent the identity its library's
        contracts name, so the card goes once more with them."""
        response = super().register(**kwargs)
        library = getattr(self, 'phema_library', None)
        if library is not None and self.plaza_token and library.ensure():
            self._force_plaza_register_once = True
            response = super().register(**kwargs)
        return response

    def _phema_changed(self, *records: Optional[Mapping[str, Any]]) -> None:
        """Plaza hears at once of a Phema kept, changed or removed here, so its owner can set its lists."""
        if self.phema_library is not None:
            self.phema_library.touched(*records)

    # ---- who is calling --------------------------------------------------------------------------------------

    def _inject_remote_caller_context_for_practice(self, **kwargs):
        """Attach the runtime's verified identity with a marker a request can't forge (it is not JSON)."""
        content = kwargs['content']
        if isinstance(content, dict):
            content = copy.deepcopy(content)
            content.pop('_caller', None)
            for key in ('params', 'input_data'):
                if isinstance(content.get(key), dict):
                    content[key].pop('_caller', None)
        result = super()._inject_remote_caller_context_for_practice(**{**kwargs, 'content': content})
        if kwargs['practice_id'] != 'get_pulse_data' or not isinstance(result, dict):
            return result
        verified = kwargs['verified']
        for item in (result, result.get('params'), result.get('input_data')):
            if isinstance(item, dict) and isinstance(item.get('_caller'), dict):
                item['_caller']['_asset_verified'] = self._asset_marker
                item['_caller']['_asset_delegation'] = copy.deepcopy(verified.get('delegation') or {})
        return result

    def _owner_account(self) -> str:
        return str(self._configuration_owner_id() or '')

    def _agent_account(self, agent_id: str, delegation: Mapping[str, Any]) -> str:
        """The calling agent's owner account as Plaza recorded it; '' when Plaza can't say (never from the request)."""
        claims = (delegation.get('authority') or {}) if isinstance(delegation, Mapping) else {}
        if isinstance(claims, Mapping) and claims.get('serviceOwnerId'):
            return str(claims['serviceOwnerId'])
        now = time.monotonic()
        with self._accounts_lock:
            known = self._accounts.get(agent_id)
            if known and known[1] > now:
                return known[0]
        account = ''
        try:
            response = self._plaza_request('get', '/api/directory/entries', timeout=5, retries=0,
                                           params={'q': agent_id, 'limit': 2, 'include_persisted': False})
            if response.status_code == 200:
                from prompits.core.agent_suspension import verified_owner
                rows = [row for row in (response.json().get('entries') or []) if row.get('agent_id') == agent_id]
                if len(rows) == 1:
                    account = verified_owner(rows[0].get('card') or {}) or ''
        except Exception as exc:  # Plaza unreachable: the caller simply has no account here
            self.logger.debug(f'Owner account of {agent_id} unavailable: {exc}')
        with self._accounts_lock:
            self._accounts[agent_id] = (account, now + ACCOUNT_SECONDS)
        return account

    def _principal(self, caller: Any) -> Principal:
        if self.asset_mode == 'local':
            return Principal(local=True)
        if not isinstance(caller, dict) or caller.get('_asset_verified') is not self._asset_marker:
            raise HTTPException(401, 'AssetStorage answers only callers Plaza has verified.')
        agent_id = str(caller.get('agent_id') or '')
        user_id = str((caller.get('user') or {}).get('id') or '')
        owner = self._owner_account()
        account = self._agent_account(agent_id, caller.get('_asset_delegation') or {}) if agent_id else ''
        if not account and user_id:
            account = user_id
        site_owner = bool(owner) and (account == owner or user_id == owner) or caller.get('auth_mode') == 'direct'
        return Principal(agent_id=agent_id, user_id=user_id, account=account, site_owner=site_owner)

    # ---- pulses ----------------------------------------------------------------------------------------------

    def get_pulse_data(self, input_data=None, pulse_name=None, pulse_address=None, output_schema=None):
        name = pulse_name or next((p.get('name') for p in self.supported_pulses
                                   if pulse_address and p.get('pulse_address') == pulse_address), None)
        if self.phema_library is not None and name in self.phema_library.operations:
            # The library's operations run only with their exact operation grant, on their own route.
            raise HTTPException(404, 'Open the Phema library from the New Data Browser.')
        if name not in PULSES:
            return super().get_pulse_data(input_data, pulse_name, pulse_address, output_schema)
        data = dict(input_data or {})
        caller = data.pop('_caller', None)
        if self.asset_mode == 'local' and caller is not None:
            raise HTTPException(422, 'Caller details are not accepted.')
        principal = self._principal(caller)
        with self._track_pulser_work(f'{name} request', f'Serving {name}.'):
            try:
                return getattr(self, '_' + name)(principal, data)
            except AssetError as exc:
                raise HTTPException(exc.status, exc.message) from None

    @staticmethod
    def _only(data: Mapping[str, Any], allowed: set) -> None:
        extra = set(data) - allowed
        if extra:
            raise AssetError(422, 'Unexpected fields: ' + ', '.join(sorted(extra)) + '.')

    def _asset_put(self, principal: Principal, data: Dict[str, Any]) -> Dict[str, Any]:
        self._only(data, {'asset_type', 'media_type', 'name', 'description', 'tags', 'labels', 'visibility',
                          'expires_at', 'source_ref', 'owner', 'replace', 'size', 'sha256', 'content_base64'})
        if 'content_base64' in data:
            # A file of one part in one call; a declared size or sha256 must match it.
            content = decode(data.pop('content_base64'))
            if data.pop('size', len(content)) != len(content):
                raise AssetError(422, 'The size does not match the content.')
            if data.pop('sha256', None) not in (None, hashlib.sha256(content).hexdigest()):
                raise AssetError(422, 'The sha256 does not match the content.')
            record = self.asset_store.put(principal, data, content)
            self._phema_changed(record)
            return {'asset': public_view(record, principal)}
        return self.asset_store.begin(principal, data)

    def _asset_put_part(self, principal: Principal, data: Dict[str, Any]) -> Dict[str, Any]:
        self._only(data, {'upload_id', 'index', 'content_base64'})
        result = self.asset_store.put_part(principal, data.get('upload_id'), data.get('index'),
                                           decode(data.get('content_base64')))
        if 'asset' in result:
            self._phema_changed(result['asset'])
            result['asset'] = public_view(result['asset'], principal)
        return result

    def _asset_get(self, principal: Principal, data: Dict[str, Any]) -> Dict[str, Any]:
        self._only(data, {'asset_id', 'offset', 'length', 'metadata_only'})
        if data.get('metadata_only') is True:
            return {'asset': public_view(self.asset_store.readable(data.get('asset_id'), principal), principal)}
        offset = data.get('offset', 0)
        record, content = self.asset_store.read(principal, data.get('asset_id'), offset, data.get('length', PART_BYTES))
        following = offset + len(content)
        return {'asset': public_view(record, principal), 'offset': offset, 'content_base64': encode(content),
                'next_offset': following if following < record['size'] else None}

    def _asset_list(self, principal: Principal, data: Dict[str, Any]) -> Dict[str, Any]:
        self._only(data, {'scope', 'owner', 'asset_type', 'tag', 'name', 'limit', 'cursor'})
        page = self.asset_store.list(principal, scope=data.get('scope', 'mine'), owner=data.get('owner', 'agent'),
                                     asset_type=data.get('asset_type'), tag=data.get('tag'), name=data.get('name'),
                                     limit=data.get('limit', 20), cursor=data.get('cursor'))
        return {'assets': [public_view(r, principal) for r in page['assets']], 'next_cursor': page['next_cursor']}

    def _asset_update(self, principal: Principal, data: Dict[str, Any]) -> Dict[str, Any]:
        self._only(data, {'asset_id', 'changes'})
        changes = data.get('changes')
        if not isinstance(changes, dict):
            raise AssetError(422, 'Send the changes as an object.')
        before = self.asset_store.record(data.get('asset_id'))
        record = self.asset_store.update(principal, data.get('asset_id'), changes)
        self._phema_changed(before, record)
        return {'asset': public_view(record, principal)}

    def _asset_delete(self, principal: Principal, data: Dict[str, Any]) -> Dict[str, Any]:
        self._only(data, {'asset_id'})
        before = self.asset_store.record(data.get('asset_id'))
        deleted = self.asset_store.delete(principal, data.get('asset_id'))
        self._phema_changed(before)
        return {'deleted': deleted, 'asset_id': data.get('asset_id')}

    def _asset_usage(self, principal: Principal, data: Dict[str, Any]) -> Dict[str, Any]:
        self._only(data, {'owner'})
        return self.asset_store.usage(self.asset_store.owner_for(principal, data.get('owner', 'agent')))

    # ---- housekeeping ----------------------------------------------------------------------------------------

    def _sweep_loop(self, seconds: int) -> None:
        while not self._sweep_stop.wait(seconds):
            try:
                removed = self.asset_store.sweep()
                if any(removed.values()):
                    self.logger.info(f'AssetStorage sweep removed {removed}')
            except Exception as exc:
                self.logger.warning(f'AssetStorage sweep failed: {exc}')
