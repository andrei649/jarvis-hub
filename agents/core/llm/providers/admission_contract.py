"""Permanent owner floor for signed model-provider code admission."""
import re
from dataclasses import replace
from urllib.parse import urlsplit

from agents.core.acquisition.sandbox_profile import AcquisitionSandboxProfile
from agents.core.automation_contracts import ContractTemplate, field_present, predicate

from . import ProviderProfile

# Provider hooks echo validated message history to the host. Keep their pinned
# sandbox output bound above the 512 KiB request allowance plus JSON framing;
# other acquisition sandboxes retain their own 32 KiB default.
PROVIDER_OUTPUT_BYTES = 896 * 1024


def provider_sandbox_profile(profile: AcquisitionSandboxProfile) -> AcquisitionSandboxProfile:
    return replace(profile, max_output_bytes=max(profile.max_output_bytes, PROVIDER_OUTPUT_BYTES))


def _bounded_admission(view, _now):
    identity = view.get('provider_id')
    if (type(identity) is not str or re.fullmatch(r'[a-z0-9][a-z0-9._:-]{0,127}', identity) is None
            or type(view.get('artifact_id')) is not str
            or re.fullmatch(r'[a-f0-9]{32}', view['artifact_id']) is None
            or type(view.get('package_hash')) is not str
            or re.fullmatch(r'[a-f0-9]{64}', view['package_hash']) is None
            or type(view.get('risk_tier')) is not int or view['risk_tier'] != 3
            or view.get('irreversible') is not True or view.get('permanent') is not True
            or view.get('phase') not in {'promote', 'execute'}):
        return False
    source, home, target = view.get('source'), view.get('home'), view.get('replacement_target')
    if (source not in {'bundled', 'legacy', 'user'}
            or (source == 'user') != (home is not None)
            or home is not None and (type(home) is not str or not home or len(home) > 256)
            or target is not None and target != identity):
        return False
    hooks = view.get('hooks')
    if (type(hooks) is not list or not hooks or len(hooks) > 16
            or any(type(h) is not str or re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,63}', h) is None
                   for h in hooks) or len(set(hooks)) != len(hooks)):
        return False
    try:
        if type(view.get('profile')) is not dict or type(view.get('sandbox')) is not dict:
            return False
        profile = ProviderProfile(**view['profile'])
        AcquisitionSandboxProfile(**view['sandbox'])
        return profile.id == identity and profile.auth_type not in {'subscription', 'oauth'}
    except (ValueError, TypeError):
        return False


PROVIDER_LOAD_CONTRACT = ContractTemplate(
    kind='plugin.load', description='Admit exact signed provider bytes after permanent owner approval.',
    constraints=(field_present('provider_id', 'artifact_id', 'package_hash', 'profile', 'hooks', 'sandbox'),
                 predicate('bounded_provider_admission', _bounded_admission,
                           reason='invalid_provider_admission')),
)


def _bounded_egress(view, _now):
    """Shape of one exact signed native request; authority lives in the lease receipt."""
    if (view.get('schema') != 'signed-provider-egress-v1'
            or type(view.get('provider_id')) is not str
            or re.fullmatch(r'[a-z0-9][a-z0-9._:-]{0,127}', view['provider_id']) is None
            or view.get('plugin') != view['provider_id']
            or type(view.get('artifact_id')) is not str
            or re.fullmatch(r'[a-f0-9]{32}', view['artifact_id']) is None
            or type(view.get('package_hash')) is not str
            or re.fullmatch(r'[a-f0-9]{64}', view['package_hash']) is None
            or view.get('source') not in {'bundled', 'legacy', 'user'}
            or type(view.get('request_sha256')) is not str
            or re.fullmatch(r'[a-f0-9]{64}', view['request_sha256']) is None
            or type(view.get('receipt_id')) is not str
            or re.fullmatch(r'[a-f0-9]{32}', view['receipt_id']) is None
            or type(view.get('model')) is not str or not view['model']
            or view.get('method') != 'POST'
            or type(view.get('risk_tier')) is not int or view['risk_tier'] != 3
            or view.get('irreversible') is not True or view.get('permanent') is not True):
        return False
    home = view.get('home')
    if ((view['source'] == 'user') != (home is not None)
            or home is not None and (type(home) is not str or not home or len(home) > 256)):
        return False
    try:
        url = urlsplit(view['url'])
        return (url.scheme == 'https' and url.hostname is not None
                and url.username is None and url.password is None and not url.fragment
                and url.netloc == view.get('authority') and url.hostname == view.get('host')
                and url.path == view.get('path') and url.query == view.get('query'))
    except (TypeError, ValueError):
        return False


PROVIDER_EGRESS_CONTRACT = ContractTemplate(
    kind='plugin.egress',
    description='One current signed provider request inside its verified dispatch lease.',
    constraints=(field_present('plugin', 'url', 'provider_id', 'artifact_id',
                               'package_hash', 'source', 'method', 'model',
                               'request_sha256', 'receipt_id'),
                 predicate('bounded_provider_egress', _bounded_egress,
                           reason='invalid_provider_egress')),
)


def _bounded_credential(view, _now):
    """Only signed-record metadata and one owner operation; never secret bytes."""
    required = {'schema', 'authority', 'home', 'provider_id', 'source',
                'artifact_id', 'package_hash', 'endpoint', 'auth_type',
                'operation', 'current_generation', 'risk_tier', 'irreversible'}
    if (type(view) is not dict or set(view) != required
            or view['schema'] != 'provider-credential-v1'
            or view['authority'] != 'local-owner-v1'
            or view['source'] not in {'user', 'legacy', 'bundled'}
            or view['auth_type'] not in {'bearer', 'api-key'}
            or view['operation'] not in {'write', 'delete'}
            or type(view['current_generation']) is not int
            or not 0 <= view['current_generation'] < 2**63 - 1
            or type(view['risk_tier']) is not int or view['risk_tier'] != 3
            or view['irreversible'] is not True
            or type(view['provider_id']) is not str
            or re.fullmatch(r'[a-z0-9][a-z0-9._:-]{0,127}', view['provider_id']) is None
            or type(view['artifact_id']) is not str
            or re.fullmatch(r'[a-f0-9]{32}', view['artifact_id']) is None
            or type(view['package_hash']) is not str
            or re.fullmatch(r'[a-f0-9]{64}', view['package_hash']) is None
            or type(view['home']) is not str or not view['home'] or len(view['home']) > 2048
            or type(view['endpoint']) is not str or len(view['endpoint']) > 2048):
        return False
    try:
        endpoint = urlsplit(view['endpoint'])
        return (endpoint.scheme == 'https' and bool(endpoint.hostname)
                and endpoint.port != 0 and endpoint.username is None
                and endpoint.password is None and not endpoint.query and not endpoint.fragment
                and all(33 <= ord(char) <= 126 for char in view['endpoint']))
    except (ValueError, TypeError):
        return False


PROVIDER_CREDENTIAL_CONTRACT = ContractTemplate(
    kind='provider.credential',
    description='Mutate one exact owner-managed signed provider credential.',
    constraints=(predicate('bounded_provider_credential', _bounded_credential,
                           reason='invalid_provider_credential'),),
)
