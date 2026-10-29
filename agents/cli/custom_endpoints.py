"""Owner CLI for named compatible endpoints; credentials enter through stdin only."""
from __future__ import annotations

import argparse
from urllib.parse import quote

BASE = '/api/admin/llm/custom-endpoints'
_ENDPOINT_FIELDS = frozenset({'key', 'identity', 'name', 'host', 'model', 'auth_type',
                              'data_policy', 'destination_class', 'revision',
                              'config_revision', 'active', 'credential_configured',
                              'credential_generation'})


def _metadata(row):
    if type(row) is not dict:
        raise argparse.ArgumentTypeError('unreadable endpoint status')
    return {key: row[key] for key in _ENDPOINT_FIELDS if key in row}


def _public_result(operation, result):
    if type(result) is not dict:
        raise argparse.ArgumentTypeError('unreadable endpoint response')
    if operation == 'list':
        rows = result.get('endpoints')
        if type(rows) is not list:
            raise argparse.ArgumentTypeError('unreadable endpoint list')
        return {'endpoints': [_metadata(row) for row in rows],
                **{key: result[key] for key in ('choice_epoch', 'active',
                    'legacy_recovery_candidate', 'unavailable') if key in result}}
    if operation in {'create', 'rename'}:
        return _metadata(result)
    allowed = {'activate': {'active', 'choice_epoch', 'revision'},
               'clear': {'active', 'choice_epoch'}, 'delete': {'deleted'},
               'validate': {'ok', 'models', 'identity'},
               'credential-status': {'configured', 'generation'},
               'credential-set': {'configured', 'generation'},
               'credential-delete': {'configured', 'generation'}}[operation]
    return {key: result[key] for key in allowed if key in result}


def register_parser(verbs):
    provider = verbs.add_parser('provider', help='owner named compatible endpoints')
    families = provider.add_subparsers(dest='family', required=True)
    custom = families.add_parser('custom', help='manage named OpenAI-compatible endpoints')
    commands = custom.add_subparsers(dest='operation', required=True)
    commands.add_parser('list', help='redacted endpoint status')
    create = commands.add_parser('create', help='create an endpoint; never probes it')
    for flag in ('key', 'name', 'base-url', 'model'):
        create.add_argument('--' + flag, required=True)
    create.add_argument('--auth-type', choices=('none', 'bearer', 'api-key'), required=True)
    create.add_argument('--data-policy', choices=('local', 'no-training', 'trains-on-inputs', 'unknown'),
                        required=True)
    create.add_argument('--grant-destination', action='store_true',
                        help='explicit owner grant for a LAN or public destination')
    rename = commands.add_parser('rename', help='change display name only')
    rename.add_argument('key')
    rename.add_argument('name')
    rename.add_argument('--revision', type=int, required=True)
    activate = commands.add_parser('activate', help='select an exact endpoint and model')
    activate.add_argument('key')
    activate.add_argument('--revision', type=int, required=True)
    activate.add_argument('--choice-epoch', type=int, required=True)
    activate.add_argument('--acknowledge-unknown-price', action='store_true')
    activate.add_argument('--acknowledge-data-policy', action='store_true')
    activate.add_argument('--grant-destination', action='store_true',
                          help='grant this exact LAN or public destination for activation')
    clear = commands.add_parser('clear', help='clear the active custom choice')
    clear.add_argument('--choice-epoch', type=int, required=True)
    remove = commands.add_parser('delete', help='delete one named endpoint')
    remove.add_argument('key')
    remove.add_argument('--revision', type=int, required=True)
    validate = commands.add_parser('validate', help='governed bounded /models probe')
    validate.add_argument('key')
    for name in ('credential-status', 'credential-set', 'credential-delete'):
        command = commands.add_parser(name, help='endpoint-scoped credential metadata or mutation')
        command.add_argument('key')
    return provider


def run(ns: argparse.Namespace, ctx) -> int:
    if ns.family != 'custom':
        raise argparse.ArgumentTypeError('unknown provider family')
    op = ns.operation
    path = BASE
    body = None
    method = 'GET'
    if op == 'create':
        method, body = 'POST', {'key': ns.key, 'name': ns.name,
                               'base_url': ns.base_url, 'model': ns.model,
                               'auth_type': ns.auth_type, 'data_policy': ns.data_policy,
                               'grant_destination': ns.grant_destination}
    elif op == 'clear':
        method, path = 'DELETE', BASE + '/active'
        body = {'expected_choice_epoch': ns.choice_epoch}
    elif op != 'list':
        path = BASE + '/' + quote(ns.key, safe='')
        if op == 'rename':
            method, body = 'PUT', {'name': ns.name, 'expected_revision': ns.revision}
        elif op == 'activate':
            method, path = 'PUT', path + '/activate'
            body = {'expected_revision': ns.revision,
                    'expected_choice_epoch': ns.choice_epoch,
                    'acknowledge_unknown_price': ns.acknowledge_unknown_price,
                    'acknowledge_data_policy': ns.acknowledge_data_policy,
                    'grant_destination': ns.grant_destination}
        elif op == 'delete':
            method, body = 'DELETE', {'expected_revision': ns.revision}
        elif op == 'validate':
            method, path = 'POST', path + '/validate'
        elif op == 'credential-status':
            path += '/credential'
        elif op == 'credential-delete':
            method, path = 'DELETE', path + '/credential'
        elif op == 'credential-set':
            method, path = 'PUT', path + '/credential'
            secret = ctx.inp.readline().rstrip('\r\n')
            if not secret:
                raise argparse.ArgumentTypeError('credential required on stdin')
            body = {'secret': secret}
        else:
            raise argparse.ArgumentTypeError('unknown custom endpoint operation')
    result = ctx.client().request(method, path, body)
    ctx.dump(_public_result(op, result))
    return 0
