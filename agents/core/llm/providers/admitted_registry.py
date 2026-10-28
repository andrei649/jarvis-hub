"""Resolve only explicitly bound, currently runnable signed provider packages.

Metadata discovery cannot select a package or change a saved credential owner.
The trusted caller supplies the exact approved hash binding for each identity.
"""
from __future__ import annotations

import hashlib
import re
from types import MappingProxyType

from .admitted_profiles import AdmittedProviderProfile
from .registry_layers import AdmissionSnapshot, LayeredRegistry


class AdmittedProviderRegistry:
    def __init__(self, builtins, candidates=(), *, packages, runtime, home=None, bindings=None):
        chosen = dict(bindings or {})
        if (len(chosen) > 256 or any(type(k) is not str or type(v) is not str
                                   or re.fullmatch(r'[a-z0-9][a-z0-9._:-]{0,127}', k) is None
                                   or re.fullmatch(r'[a-f0-9]{64}', v) is None
                                   for k, v in chosen.items())):
            raise ValueError('invalid approved provider bindings')
        self._bindings = MappingProxyType(chosen)
        self._packages, self._runtime, self._home = packages, runtime, home
        admissions = []
        candidates = tuple(candidates)
        if len(candidates) > 256:
            raise ValueError('provider candidate count exceeds limit')
        for candidate in candidates:
            if candidate.id not in chosen or candidate.source == 'pip':
                continue
            try:
                admission = AdmissionSnapshot(candidate.id, candidate.source, candidate.home,
                                              candidate.digest, candidate.replacement_target)
                if self._live(admission):
                    admissions.append(admission)
            except (ValueError, TypeError):
                continue
        self._view = LayeredRegistry(builtins, candidates, admissions=admissions,
                                     home=home, is_live=self._live)

    def _record(self, admission):
        record = self._packages.require_runnable(
            admission.provider_id, expected_hash=self._bindings[admission.provider_id],
            home=self._home if admission.source == 'user' else None)
        raw = dict(record.members).get('provider.json')
        if (record.provider_id != admission.provider_id or record.source != admission.source
                or record.home != admission.home or record.replacement_target != admission.replacement_target
                or type(raw) is not bytes or hashlib.sha256(raw).hexdigest() != admission.digest):
            raise KeyError('signed provider scope differs from candidate')
        return record

    def _live(self, admission):
        try:
            self._record(admission)
            return True
        except Exception:
            return False

    def canonical_id(self, provider_id):
        return self._view.canonical_id(provider_id)

    def get(self, provider_id):
        entry = self._view.get(provider_id)
        if entry.profile is not None:
            return entry.profile
        try:
            record = self._record(entry.admission)
            if record.profile.id != entry.id or record.profile.aliases != entry.aliases:
                raise KeyError('signed profile identity changed')
            return AdmittedProviderProfile.from_record(record, self._runtime)
        except Exception:
            raise KeyError('provider admission is no longer runnable') from None

    def list(self):
        result = []
        for entry in self._view.list():
            try:
                result.append(self.get(entry.id))
            except KeyError:
                continue
        return result
