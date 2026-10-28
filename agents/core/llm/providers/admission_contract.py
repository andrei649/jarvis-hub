"""Permanent owner floor for signed model-provider code admission."""
import re
from dataclasses import replace

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
