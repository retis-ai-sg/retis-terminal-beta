"""A Terminal tab's own look: its custom theme colors, its session name and where each Phema's window opens."""
import re

from fastapi import HTTPException

COLOR = re.compile(r'#[0-9a-fA-F]{6}')
COLORS = ('accent', 'background', 'surface', 'text')


def validate_custom_theme(value):
    if (not isinstance(value, dict) or set(value) != {'base', *COLORS} or value['base'] not in ('dark', 'light')
            or not all(isinstance(value[key], str) and COLOR.fullmatch(value[key]) for key in COLORS)):
        raise HTTPException(422, 'Choose a dark or light base and four #rrggbb colors.')


def session_name(value):
    """The name shown in this tab's title bar and browser tab; empty clears it."""
    if not isinstance(value, str):
        raise HTTPException(422, 'Enter a session name.')
    value = value.strip()
    if len(value) > 60 or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise HTTPException(422, 'Use up to 60 characters for the session name.')
    return value


PHEMA_WINDOWS = 100
PLACE = ('phema', 'x', 'y', 'width', 'height', 'maximized', 'at')


def phema_windows(value):
    """Where this window last showed each Phema's window: one row per Phema (its id), with the frame in CSS pixels and
    whether it was maximized, newest 100. The Terminal keeps them as they come; it knows nothing of the Phemas."""
    number = lambda item, low: type(item) in (int, float) and low <= item <= 100_000
    if (not isinstance(value, list) or len(value) > PHEMA_WINDOWS
            or any(not isinstance(row, dict) or set(row) != set(PLACE)
                   or not isinstance(row['phema'], str) or not 1 <= len(row['phema']) <= 200
                   or not number(row['x'], 0) or not number(row['y'], 0)
                   or not number(row['width'], 1) or not number(row['height'], 1)
                   or not isinstance(row['maximized'], bool)
                   or type(row['at']) is not int or not 0 < row['at'] < 10 ** 14 for row in value)
            or len({row['phema'] for row in value}) != len(value)):
        raise HTTPException(422, 'Keep each Phema window\'s place once: its Phema, position, size, whether it is maximized and when.')
    return [{key: row[key] for key in PLACE} for row in value]
