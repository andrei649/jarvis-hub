from agents.core.capability_manifests import ACTION_CAPABILITY_MANIFESTS
from agents.core.kernel.registry import ACTION_REGISTRY, Mediation, known_broker_action_kinds
from agents.core.llm.providers.admission_contract import PROVIDER_LOAD_CONTRACT


def test_provider_admission_has_real_kernel_classification_and_manifest():
    assert ACTION_REGISTRY['plugin.load'] is Mediation.KERNEL
    assert 'plugin.load' in known_broker_action_kinds()
    manifest = ACTION_CAPABILITY_MANIFESTS['plugin.load']
    assert manifest.contract_ref.endswith(':PROVIDER_LOAD_CONTRACT')
    assert manifest.risk == 'irreversible_or_money'


def test_provider_load_contract_refuses_missing_identity_or_owner_floor():
    for payload in ({}, {'provider_id': 'x', 'risk_tier': 3, 'permanent': True},
                    {'provider_id': 'x', 'risk_tier': True, 'permanent': True}):
        assert not PROVIDER_LOAD_CONTRACT.evaluate(payload).admissible
