"""Bounded Action Kernel shape for owner-managed custom endpoint mutations."""
from __future__ import annotations

import re

from agents.core.automation_contracts import ContractTemplate, predicate

from .custom_endpoints import classify_url


def _bounded_custom(view, _now):
    required = {'schema', 'authority', 'home', 'operation', 'key', 'base_url',
                'model', 'auth_type', 'data_policy', 'destination_class',
                'config_revision', 'choice_epoch', 'credential_generation',
                'unknown_price_ack', 'data_policy_ack', 'grant_destination',
                'risk_tier', 'irreversible'}
    if (type(view) is dict and set(view) == required and view.get('schema') == 'custom-endpoint-v1'
            and view.get('authority') == 'custom-endpoint-owner-v1'
            and view.get('operation') == 'clear' and view.get('key') == 'recovery'
            and view.get('base_url') == '' and view.get('model') == ''
            and view.get('auth_type') == 'none' and view.get('data_policy') == 'unknown'
            and view.get('destination_class') == 'recovery'
            and view.get('config_revision') == 0 and view.get('credential_generation') == 0
            and type(view.get('choice_epoch')) is int and view['choice_epoch'] >= 0
            and view.get('unknown_price_ack') is False
            and view.get('data_policy_ack') is False
            and view.get('grant_destination') is False
            and type(view.get('risk_tier')) is int and view['risk_tier'] == 3
            and view.get('irreversible') is True
            and type(view.get('home')) is str and 1 <= len(view['home']) <= 2048):
        return True
    if (type(view) is not dict or set(view) != required
            or view['schema'] != 'custom-endpoint-v1'
            or view['authority'] != 'custom-endpoint-owner-v1'
            or view['operation'] not in {'create', 'activate', 'rename', 'delete', 'clear',
                                        'credential_write', 'credential_delete', 'validate'}
            or type(view['home']) is not str or not 1 <= len(view['home']) <= 2048
            or type(view['key']) is not str
            or re.fullmatch(r'[a-z0-9][a-z0-9._-]{0,63}', view['key']) is None
            or type(view['config_revision']) is not int or view['config_revision'] < 1
            or type(view['choice_epoch']) is not int or view['choice_epoch'] < 0
            or type(view['credential_generation']) is not int or view['credential_generation'] < 0
            or type(view['unknown_price_ack']) is not bool
            or type(view['data_policy_ack']) is not bool
            or type(view['grant_destination']) is not bool
            or view['risk_tier'] != 3 or type(view['risk_tier']) is not int
            or view['irreversible'] is not True
            or view['auth_type'] not in {'none', 'bearer', 'api-key'}
            or view['data_policy'] not in {'local', 'no-training', 'trains-on-inputs', 'unknown'}
            or type(view['model']) is not str or not 1 <= len(view['model']) <= 256):
        return False
    try:
        kind = classify_url(view['base_url'])
        return (kind == view['destination_class']
                and (kind == 'loopback' or view['operation'] not in {'create', 'activate'}
                     or view['grant_destination'] is True))
    except Exception:
        return False


CUSTOM_ENDPOINT_CONTRACT = ContractTemplate(
    kind='provider.custom_endpoint',
    description='One exact live owner custom endpoint decision.',
    constraints=(predicate('bounded_custom_endpoint', _bounded_custom,
                           reason='invalid_custom_endpoint'),),
)
