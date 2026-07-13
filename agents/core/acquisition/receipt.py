"""Immutable, hash-bound receipts for acquisition sandbox verification."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass

from .generator import CapabilityContract, GeneratedPackage


def canonical_hash(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class VerificationReceipt:
    receipt_version: int
    artifact_id: str
    request_id: str
    package_hash: str
    source_hash: str
    test_hash: str
    plan_hash: str
    goal_hash: str
    contract_hash: str
    model_route: str
    runtime_image: str
    runtime_config_hash: str
    generated_test_output_hash: str
    contract_output_hash: str
    mutation_output_hash: str
    generated_test_exit: int
    contract_exit: int
    mutation_exit: int
    started_at: float
    finished_at: float
    receipt_hash: str

    def canonical_payload(self) -> dict:
        return {key: value for key, value in asdict(self).items() if key != "receipt_hash"}


def make_receipt(
    *,
    package: GeneratedPackage,
    contract: CapabilityContract,
    profile,
    generated_test_output: str,
    contract_output: str,
    mutation_output: str,
    generated_test_exit: int,
    contract_exit: int,
    mutation_exit: int,
    started_at: float,
    finished_at: float,
) -> VerificationReceipt:
    payload = {
        "receipt_version": 1,
        "artifact_id": package.artifact_id,
        "request_id": package.request_id,
        "package_hash": package.package_hash,
        "source_hash": package.source_hash,
        "test_hash": package.test_hash,
        "plan_hash": package.plan_hash,
        "goal_hash": package.goal_hash,
        "contract_hash": contract.contract_hash,
        "model_route": package.model_route,
        "runtime_image": profile.image,
        "runtime_config_hash": profile.config_hash,
        "generated_test_output_hash": canonical_hash(generated_test_output),
        "contract_output_hash": canonical_hash(contract_output),
        "mutation_output_hash": canonical_hash(mutation_output),
        "generated_test_exit": int(generated_test_exit),
        "contract_exit": int(contract_exit),
        "mutation_exit": int(mutation_exit),
        "started_at": float(started_at),
        "finished_at": float(finished_at),
    }
    return VerificationReceipt(receipt_hash=canonical_hash(payload), **payload)


def receipt_is_current(
    receipt: VerificationReceipt,
    package: GeneratedPackage,
    contract: CapabilityContract,
    profile,
) -> bool:
    if not isinstance(receipt, VerificationReceipt):
        return False
    source_hash = hashlib.sha256(package.code.encode("utf-8")).hexdigest()
    test_hash = hashlib.sha256(package.test_code.encode("utf-8")).hexdigest()
    package_hash = canonical_hash(package.canonical_members())
    expected = {
        "artifact_id": package.artifact_id,
        "request_id": package.request_id,
        "package_hash": package.package_hash,
        "source_hash": package.source_hash,
        "test_hash": package.test_hash,
        "plan_hash": package.plan_hash,
        "goal_hash": package.goal_hash,
        "contract_hash": contract.contract_hash,
        "model_route": package.model_route,
        "runtime_image": profile.image,
        "runtime_config_hash": profile.config_hash,
    }
    payload = receipt.canonical_payload()
    return (
        package.source_hash == source_hash
        and package.test_hash == test_hash
        and package.package_hash == package_hash
        and package.model_route == "strict-local"
        and all(payload.get(key) == value for key, value in expected.items())
        and receipt.generated_test_exit == 0
        and receipt.contract_exit == 0
        and receipt.mutation_exit != 0
        and receipt.finished_at >= receipt.started_at
        and receipt.receipt_hash == canonical_hash(payload)
    )


__all__ = [
    "VerificationReceipt",
    "canonical_hash",
    "make_receipt",
    "receipt_is_current",
]
