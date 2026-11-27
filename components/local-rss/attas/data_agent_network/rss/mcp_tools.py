"""The Local RSS operations an AI app on this computer may call over MCP (phemacast.network.mcp).

Only reading: the feeds and groups the user follows, the articles Local RSS keeps for them, and one article in full.
Nothing that changes subscriptions, reads feeds now, reaches another RSS source or asks the Terminal for data is
offered. Each tool runs Local RSS's own `rss_local` operation, exactly as its RSS Viewer does.
"""
from copy import deepcopy
from uuid import uuid4

from phemacast.network.mcp import LocalTool

from .contracts import LOCAL_OPERATIONS, LOCAL_PULSE

# An AI app that names no limit gets this many articles, not the viewer's 300.
DEFAULT_ARTICLES = 50


def _envelope(operation, defaults=None):
    """The `rss_local` envelope for one operation; each call gets its own request key."""
    def parameters(arguments):
        return {'operation': operation, 'parameters': {**(defaults or {}), **arguments},
                'request_key': 'mcp-' + uuid4().hex}
    return parameters


def _answer(value):
    """What the operation answered, or its refusal as the tool's error."""
    from prompits.mcp.server import ToolFailure
    if not isinstance(value, dict):
        return value
    if value.get('error'):
        raise ToolFailure(str(value['error']))
    return value.get('response', value)


def _tool(name, description, defaults=None):
    return LocalTool(name=name, operation=LOCAL_PULSE, description=description,
                     input_schema=deepcopy(LOCAL_OPERATIONS[name]), parameters=_envelope(name, defaults),
                     answer=_answer, read_only=True, idempotent=True, open_world=False)


TOOLS = (
    _tool('rss_subscriptions',
          "The feeds and feed groups this computer's Local RSS follows: each feed's address, name and group, how "
          'often it is read and how its last read went.'),
    _tool('rss_articles',
          'The newest articles Local RSS keeps for the feeds it follows, newest first, each with its feed, title, link, '
          'date and a short summary. Narrow it with `group` (a group key from rss_subscriptions) or `feed` (a feed '
          f'address); `limit` is 1-500, {DEFAULT_ARTICLES} when left out.',
          {'limit': DEFAULT_ARTICLES}),
    _tool('rss_article',
          'One kept article in full (title, link, date, author, summary and content), by its `feed` address and `id` '
          'from rss_articles.'),
)
