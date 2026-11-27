"""Send feedback: one message from a window's Plaza account to its site's `support` receiver, delivered by that Plaza.

The Terminal holds no mail settings and keeps nothing. It checks what the window sends, writes it as plain text and
asks its Plaza, as the window's own account, to deliver it to the receiver the site configured. The receiver, its
mailbox, its limits and the removal of credentials from the text are the Plaza's; the Terminal never names a route,
provider or address other than the reply address the viewer typed.
"""
from __future__ import annotations

import re

RECEIVER = 'support'
EVENT = 'feedback'
CATEGORIES = {'bug': 'Bug', 'idea': 'Idea', 'question': 'Question'}
LANGUAGES = ('en', 'zh-Hant', 'zh-Hans', 'ja', 'es', 'fr')
MESSAGE_CHARACTERS = 5000
EMAIL = re.compile(r'^[^@\s<>()\[\],;:"\\]{1,64}@[A-Za-z0-9](?:[A-Za-z0-9-]{0,62}[A-Za-z0-9])?'
                   r'(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,62}[A-Za-z0-9])?)+$')
HOST = re.compile(r'^[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?(?::[0-9]{1,5})?$')
VERSION = re.compile(r'^[A-Za-z0-9][A-Za-z0-9 ._+()-]{0,39}$')
CONTROL = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')
DETAILS = (('terminal_version', 'Terminal version'), ('language', 'Language'), ('plaza_host', 'Plaza host'),
           ('phema_name', 'Current Phema'))


def one_line(value, limit):
    text = ' '.join(CONTROL.sub('', str(value or '')).split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + '…'


def checked(body):
    """The request a window may send, or ValueError saying what is wrong. Unknown fields are refused."""
    if not isinstance(body, dict) or not set(body) <= {'category', 'message', 'reply_to', 'details'}:
        raise ValueError('Send a category, a message and, if you like, a reply address and technical details.')
    category = body.get('category')
    if category not in CATEGORIES:
        raise ValueError('Choose bug, idea or question.')
    message = body.get('message')
    if not isinstance(message, str) or not message.strip():
        raise ValueError('Write a message first.')
    if len(message) > MESSAGE_CHARACTERS:
        raise ValueError(f'Keep the message to {MESSAGE_CHARACTERS} characters.')
    reply_to = body.get('reply_to') or ''
    if not isinstance(reply_to, str) or (reply_to and (len(reply_to) > 254 or not EMAIL.match(reply_to))):
        raise ValueError('Enter one email address to reply to.')
    details = body.get('details')
    if details is not None and (not isinstance(details, dict) or not set(details) <= {key for key, _ in DETAILS}
                                or any(not isinstance(value, str) for value in details.values())):
        raise ValueError('Technical details are the Terminal version, language, Plaza host and current Phema only.')
    kept = {}
    for key, _ in DETAILS:
        raw = str((details or {}).get(key) or '').strip()
        # The version, language and host must be exactly what the Terminal shows; the Phema name is free text.
        value = one_line(raw, 120) if key == 'phema_name' else raw
        if not value or (key == 'terminal_version' and not VERSION.match(value)) \
                or (key == 'language' and value not in LANGUAGES) or (key == 'plaza_host' and not HOST.match(value)):
            continue
        kept[key] = value
    return {'category': category, 'message': message.replace('\r\n', '\n').strip(), 'reply_to': reply_to, 'details': kept}


def notification(request):
    """The Plaza notification for one checked request: plain text, addressed to the site's support receiver."""
    label = CATEGORIES[request['category']]
    first = one_line(request['message'].splitlines()[0], 80)
    lines = [f'Category: {label}', '', request['message'], '']
    if request['details']:
        lines.append('Technical details (shown to the sender before sending):')
        lines += [f'  {title}: {request["details"][key]}' for key, title in DETAILS if key in request['details']]
    else:
        lines.append('Technical details: not included by the sender.')
    return {'receiver': RECEIVER, 'event_type': EVENT, 'render_mode': 'direct', 'title': f'{label}: {first}',
            'message': '\n'.join(lines) + '\n', **({'reply_to': request['reply_to']} if request['reply_to'] else {})}


def answer(status_code, value, *, reply_to):
    """What the window is told, from Plaza's answer: sent, held by the limit, or why it was not sent."""
    if status_code in (401, 403):
        return 401, {'detail': 'Plaza session expired. Sign in again.'}
    if status_code in (404, 405):
        return 409, {'detail': 'This site does not take feedback yet.'}
    if status_code == 503:
        return 503, {'detail': 'Plaza is starting. Try again in a moment.'}
    if not 200 <= status_code < 300 or not isinstance(value, dict):
        return 502, {'detail': 'Plaza could not send it. Try again later.'}
    status = value.get('status')
    if status == 'sent':
        return 200, {'status': 'sent', **({'replyTo': reply_to} if reply_to else {})}
    if status == 'limited':
        held = [d for d in value.get('deliveries') or [] if isinstance(d, dict) and d.get('status') == 'limited']
        first = held[0] if held else {}
        retry = first.get('retry_at')
        return 200, {'status': 'limited', 'window': 'day' if first.get('window') == 'day' else 'hour',
                     'count': int(first.get('count') or 0), **({'retryAt': int(float(retry) * 1000)} if retry else {})}
    if status == 'skipped':
        return 409, {'detail': 'This site does not take feedback yet.'}
    return 502, {'detail': 'Plaza could not send it. Try again later.'}
