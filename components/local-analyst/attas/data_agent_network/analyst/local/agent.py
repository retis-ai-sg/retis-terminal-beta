"""The Local Analyst pulser: a processor and a data source on the person's own computer, used only by its Terminal.

It never registers with Plaza and holds no key and no schedule: the view's choices stay in the Terminal, the runs are
the Terminal's scheduled runs, and the results go to the AssetStorage the person picks. A stock rule's opinions are
also kept in its own state folder (index.py), which it serves as a data source (source.py) for the sentiment strategies.
"""
from pathlib import Path

from fastapi import HTTPException
from phemacast.agents.pulser import Pulser

from . import source
from .contracts import NAME, PULSE, definition
from .run import dispatch


class LocalAnalyst(Pulser):
    PIT_TYPE = 'Processor'

    def __init__(self, config, *, index=None, **kwargs):
        self.index = index
        config = {**dict(config), 'supported_pulses': [definition(), *source.pulse_definitions()], 'role': 'processor',
                  'pit_type': self.PIT_TYPE}
        kwargs.setdefault('auto_register', False)
        super().__init__(config=config, **kwargs)

    def apply_pulser_config(self, config_data=None, **kwargs):
        super().apply_pulser_config({**dict(config_data or {}), 'pit_type': self.PIT_TYPE, 'role': 'processor'}, **kwargs)
        self.agent_card.update(pit_type=self.PIT_TYPE, role='processor')
        # The Terminal lists it by its data source and plans by its spec (source.py).
        self.agent_card.setdefault('meta', {}).update(source.card_meta())

    def get_pulse_data(self, input_data=None, pulse_name=None, pulse_address=None, output_schema=None):
        name = pulse_name or (pulse_address.removeprefix('attas:') if pulse_address else PULSE)
        if not isinstance(input_data, dict) or name not in (PULSE, *source.DATA_PULSES):
            raise HTTPException(422, 'Choose a Local Analyst operation with object input.')
        data = {key: value for key, value in input_data.items() if key != '_caller'}
        if name != PULSE:
            try:
                return source.answer(name, data, self.index)
            except ValueError as error:
                return {'status': 'failed', 'source': source.public_source(), 'data': {'items': []}, 'error': str(error)[:300]}
        return dispatch(data, index=self.index)


def build(network, releases, opinions=None):
    """The pulser for this computer and its local resource, serving the Analyst Sentiment view and Phema, and the
    opinions its stock rules keep in `opinions` (a SQLite file in its state folder)."""
    from phemacast.network.pulser import install_pulser_local
    from phemacast.network.service import endpoint
    from .index import OpinionIndex
    from .release import VIEW, shipped
    pulser = LocalAnalyst({'name': NAME, 'host': '127.0.0.1', 'port': network['port'], 'plaza_url': '',
                           'description': 'Tags and scores news with the analysts you choose, keeps the results in your '
                                          'AssetStorage, and serves the stock opinions to your sentiment strategies.',
                           'local_network': network}, index=OpinionIndex(opinions) if opinions else None)
    publisher = 'local-' + network['resourceId']
    directory, manifest = VIEW.capture(publisher, endpoint(network)['url'].rstrip('/'), Path(releases), dependencies=None)
    VIEW.advertise(pulser.agent_card, manifest)
    return pulser, install_pulser_local(pulser, views={manifest['release']: directory}, phemas=shipped(publisher))
