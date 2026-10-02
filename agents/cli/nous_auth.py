"""Owner-side Nous device login; access and refresh credentials stay on the hub."""

from __future__ import annotations

import argparse
import re
import time
from urllib.parse import urlencode, urlsplit

PREFIX = '/api/oauth/nous'


def _profile(value: str) -> str:
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', value):
        raise argparse.ArgumentTypeError('profile must be 1–64 letters, digits, underscores or hyphens')
    return value


def configure_parser(verbs) -> None:
    auth = verbs.add_parser('auth', help='connect provider accounts on the hub')
    providers = auth.add_subparsers(dest='auth_provider', required=True)
    nous = providers.add_parser('nous', help='Nous account login, local status and logout')
    actions = nous.add_subparsers(dest='auth_action', required=True)
    for name in ('status', 'login', 'logout'):
        command = actions.add_parser(name)
        command.add_argument('--profile', default='default', type=_profile)
        if name != 'login':
            command.add_argument('--json', action='store_true')


def _text(value, limit=2048) -> str:
    if not isinstance(value, str) or not value or len(value) > limit or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError('invalid account response')
    return value


def _number(value, low, high) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ValueError('invalid account response')
    return value


def _status(payload, profile):
    fields = ('authenticated', 'usable', 'has_refresh_token')
    if not isinstance(payload, dict) or any(type(payload.get(k)) is not bool for k in fields):
        raise ValueError('invalid account response')
    return {'profile': profile, **{k: payload[k] for k in fields}}


def run(ns, ctx) -> int:
    # Imported at invocation to keep the CLI command tree free of import cycles.
    from .nerva import EXIT_FAILED, EXIT_OK, EXIT_UNAVAILABLE

    hub = ctx.client()
    try:
        if ns.auth_action != 'login':
            result = (hub.get(PREFIX + '/status?' + urlencode({'profile': ns.profile}))
                      if ns.auth_action == 'status' else hub.post(PREFIX + '/logout', {'profile': ns.profile}))
            public = _status(result, ns.profile)
            if ns.json:
                ctx.dump(public)
            else:
                state = 'ready' if public['usable'] else 'signed in; refresh needed' if public['authenticated'] else 'not signed in'
                ctx.say(f'Nous ({ns.profile}): {state}')
            return EXIT_OK
        start = hub.post(PREFIX + '/login', {'profile': ns.profile})
        if not isinstance(start, dict):
            raise ValueError('invalid account response')
        login_id = _text(start.get('login_id'), 128)
        code = _text(start.get('user_code'), 128)
        uri = _text(start.get('verification_uri_complete') or start.get('verification_uri'))
        parsed = urlsplit(uri)
        if (parsed.scheme not in ('https', 'http') or not parsed.hostname or parsed.username or parsed.password
                or parsed.fragment or (parsed.scheme == 'http' and parsed.hostname not in ('localhost', '127.0.0.1', '::1'))):
            raise ValueError('invalid account response')
        expires = _number(start.get('expires_in'), 1, 1800)
        delay = _number(start.get('interval'), 1, 60)
        deadline = time.monotonic() + expires
        ctx.say(f'Open {uri}\nEnter code: {code}\nWaiting for Nous authorization. Press Ctrl-C to stop waiting.')
        ctx.out.flush()
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                ctx.err.write('Nous login expired; run login again.\n')
                return EXIT_FAILED
            time.sleep(min(delay, left))
            left = deadline - time.monotonic()
            if left <= 0:
                continue
            result = hub.post(PREFIX + '/poll', {'profile': ns.profile, 'login_id': login_id}, timeout=min(30, left))
            if not isinstance(result, dict):
                raise ValueError('invalid account response')
            state = result.get('state')
            if state == 'complete':
                ctx.say(f'Nous ({ns.profile}): signed in. Model routing is unchanged.')
                return EXIT_OK
            if state == 'expired':
                ctx.err.write('Nous login expired; run login again.\n')
                return EXIT_FAILED
            if state != 'pending':
                raise ValueError('invalid account response')
            delay = _number(result.get('retry_after'), 1, 60)
    except (ValueError, TypeError):
        ctx.err.write('Nous account response was invalid; no credentials were displayed.\n')
        return EXIT_UNAVAILABLE
