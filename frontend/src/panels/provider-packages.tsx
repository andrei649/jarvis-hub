import React, { useCallback, useEffect, useState } from 'react';
import { apiDeleteBody, apiGet, apiPost, apiPut } from '../api/client';
import { Card, Row, Tag, asLive, inpS, mono } from '../panel-kit';

type PackageStatus = {
  enabled: boolean;
  runtime_present: boolean;
  selects_model: boolean;
};

type ProfileSummary = {
  id: string;
  endpoint?: { scheme: string; host: string; port: number | null };
  backend_kind: string;
  api_mode: string;
  auth?: { type: string; configured: boolean };
  capabilities?: string[];
  data_policy?: { policy: string };
  supports_health_check?: boolean;
  supports_model_listing?: boolean;
};

type PackagePreview = {
  artifact_id: string;
  provider_id: string;
  package_hash: string;
  source: string;
  replacement_target: string | null;
  hooks: string[];
  endpoint_host: string;
  auth_type: string;
  backend_kind: string;
  profile_summary: ProfileSummary;
  sandbox_image: string;
  sandbox?: Record<string, unknown>;
  member_count: number;
  member_bytes: number;
  proposal_id?: string;
  lifecycle_status?: string;
  declared_models?: string[];
};

type ProposeResult = PackagePreview & { proposal_id: string; status: string };
type DecisionResult = { proposal_id: string; status: string };
type PromoteResult = PackagePreview & { status: string };
type RevokeResult = { provider_id: string; status: string };
type CredentialStatus = { configured: boolean; generation: number };
type SelectionStatus = {
  status: 'unselected' | 'selected' | 'stale';
  provider?: string;
  model?: string;
  package_hash?: string;
  revision?: number;
  credential_generation?: number;
};

type Banner = { kind: 'ok' | 'error'; text: string } | null;

const BACKEND_KINDS = [
  'openai-compatible',
  'deepinfra-chat',
  'openai-responses',
  'xai-responses',
  'gemini',
  'anthropic',
  'openai-compatible-local',
  'ollama',
] as const;

const API_MODES = [
  'chat_completions',
  'responses',
  'gemini_generate_content',
  'anthropic_messages',
] as const;

function formatRefusal(err: unknown): string {
  const response = err as {
    status?: number;
    body?: { error?: string; reason?: string; detail?: unknown; needs?: string[] };
  };
  const status = response?.status || 'error';
  const body = response?.body;
  let code = 'request_failed';
  if (typeof body?.error === 'string' && body.error.trim()) {
    code = body.error.trim();
  } else if (typeof body?.reason === 'string' && body.reason.trim()) {
    code = body.reason.trim();
  } else if (typeof body?.detail === 'string' && body.detail.trim()) {
    code = body.detail.trim();
  } else if (body?.detail != null) {
    try {
      code = JSON.stringify(body.detail);
    } catch {
      code = 'request_failed';
    }
  }
  const needs = Array.isArray(body?.needs) && body.needs.length
    ? ` · needs ${body.needs.join(', ')}`
    : '';
  return `refused · HTTP ${status} · ${code}${needs}`;
}

const sectionBox: React.CSSProperties = {
  border: '1px solid var(--panel-line)',
  borderRadius: 4,
  padding: 10,
  marginTop: 10,
};

const fieldGrid: React.CSSProperties = {
  display: 'grid',
  gridTemplateColumns: 'repeat(auto-fit, minmax(190px, 1fr))',
  gap: 8,
  marginTop: 6,
};

const labelStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: 3,
  fontSize: 11,
  color: 'var(--ink-2)',
};

export function ProviderPackagesPanel() {
  const [pkgStatus, setPkgStatus] = useState<PackageStatus | null>(null);
  const [statusError, setStatusError] = useState('');
  const [selection, setSelection] = useState<SelectionStatus | null>(null);
  const [selectionRefusal, setSelectionRefusal] = useState('');
  const [busy, setBusy] = useState(false);
  const [banner, setBanner] = useState<Banner>(null);

  const [packages, setPackages] = useState<Record<string, PackagePreview>>({});
  const [selectedArtifactId, setSelectedArtifactId] = useState('');
  const [inspectInput, setInspectInput] = useState('');

  const [stageForm, setStageForm] = useState({
    candidate: 'addon',
    source: 'user' as 'user' | 'legacy' | 'bundled',
    providerId: '',
    displayName: '',
    baseUrl: '',
    backendKind: 'openai-compatible',
    apiMode: 'chat_completions',
    authType: 'bearer',
    dataPolicy: 'unknown',
    capabilities: 'chat,cloud',
    models: '',
    hooks: 'build_headers',
    replacementTarget: '',
  });

  const [proposeArtifactId, setProposeArtifactId] = useState('');
  const [decisionProposalId, setDecisionProposalId] = useState('');
  const [decisionArtifactId, setDecisionArtifactId] = useState('');
  const [decisionHash, setDecisionHash] = useState('');
  const [permanentConsent, setPermanentConsent] = useState(false);
  const [revokeProviderId, setRevokeProviderId] = useState('');

  const [credProvider, setCredProvider] = useState('');
  const [credHash, setCredHash] = useState('');
  const [credSecret, setCredSecret] = useState('');
  const [credStatus, setCredStatus] = useState<CredentialStatus | null>(null);

  const [selProvider, setSelProvider] = useState('');
  const [selHash, setSelHash] = useState('');
  const [selModel, setSelModel] = useState('');
  const [expectedRevision, setExpectedRevision] = useState('0');
  const [ackUnknownPrice, setAckUnknownPrice] = useState(false);
  const [ackDataPolicy, setAckDataPolicy] = useState(false);

  const syncFromPreview = useCallback((preview: PackagePreview, declaredModels?: string[]) => {
    setSelectedArtifactId(preview.artifact_id);
    setProposeArtifactId(preview.artifact_id);
    setDecisionArtifactId(preview.artifact_id);
    setDecisionHash(preview.package_hash);
    if (preview.proposal_id) {
      setDecisionProposalId(preview.proposal_id);
    }
    setRevokeProviderId(preview.provider_id);
    setCredProvider(preview.provider_id);
    setCredHash(preview.package_hash);
    setSelProvider(preview.provider_id);
    setSelHash(preview.package_hash);
    if (declaredModels && declaredModels.length > 0) {
      setSelModel(declaredModels[0]);
    } else if (preview.declared_models && preview.declared_models.length > 0) {
      setSelModel(preview.declared_models[0]);
    }
  }, []);

  const upsertPackage = useCallback((preview: PackagePreview) => {
    setPackages((prev) => {
      const existing = prev[preview.artifact_id];
      return {
        ...prev,
        [preview.artifact_id]: {
          ...existing,
          ...preview,
          proposal_id: preview.proposal_id ?? existing?.proposal_id,
          lifecycle_status: preview.lifecycle_status ?? existing?.lifecycle_status ?? 'staged',
          declared_models: preview.declared_models ?? existing?.declared_models,
        },
      };
    });
  }, []);

  const reload = useCallback(async () => {
    const [statusOutcome, selectionOutcome] = await Promise.allSettled([
      apiGet<PackageStatus>('/api/llm/provider-packages/status', { admin: true }),
      apiGet<SelectionStatus>('/api/admin/llm/provider-selection', { admin: true }),
    ]);
    if (statusOutcome.status === 'fulfilled') {
      setPkgStatus(statusOutcome.value);
      setStatusError('');
    } else {
      setStatusError(formatRefusal(statusOutcome.reason));
    }
    if (selectionOutcome.status === 'fulfilled') {
      const sel = selectionOutcome.value;
      setSelection(sel);
      setSelectionRefusal('');
      setExpectedRevision(String(typeof sel.revision === 'number' ? sel.revision : 0));
      if (sel.provider) setSelProvider(sel.provider);
      if (sel.package_hash) setSelHash(sel.package_hash);
      if (sel.model) setSelModel(sel.model);
    } else {
      setSelectionRefusal(formatRefusal(selectionOutcome.reason));
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  const runAction = async (
    operation: () => Promise<string>,
    opts: { clearSecret?: boolean; resetConsent?: boolean; refreshSelection?: boolean } = {},
  ) => {
    setBusy(true);
    setBanner(null);
    try {
      const okMessage = await operation();
      if (opts.clearSecret) setCredSecret('');
      if (opts.resetConsent) setPermanentConsent(false);
      if (opts.refreshSelection) await reload();
      setBanner({ kind: 'ok', text: okMessage });
    } catch (err) {
      if (opts.clearSecret) setCredSecret('');
      if (opts.resetConsent) setPermanentConsent(false);
      setBanner({ kind: 'error', text: formatRefusal(err) });
      if (opts.refreshSelection) {
        try {
          await reload();
        } catch {
          /* preserve refusal banner */
        }
      }
    } finally {
      setBusy(false);
    }
  };

  const handleInspect = (event: React.FormEvent) => {
    event.preventDefault();
    const targetArtifact = inspectInput.trim();
    if (!targetArtifact) return;
    void runAction(async () => {
      const preview = await apiGet<PackagePreview>(`/api/llm/provider-packages/${encodeURIComponent(targetArtifact)}`, { admin: true });
      const enriched: PackagePreview = { ...preview, lifecycle_status: preview.lifecycle_status || 'inspected' };
      upsertPackage(enriched);
      syncFromPreview(enriched);
      return `Inspected artifact ${preview.artifact_id} (${preview.provider_id})`;
    });
  };

  const handleStage = (event: React.FormEvent) => {
    event.preventDefault();
    const declaredModels = stageForm.models.split(',').map((m) => m.trim()).filter(Boolean);
    const capabilities = stageForm.capabilities.split(',').map((c) => c.trim()).filter(Boolean);
    const hooks = stageForm.hooks.split(',').map((h) => h.trim()).filter(Boolean);
    const stageBody = {
      candidate: stageForm.candidate.trim(),
      source: stageForm.source,
      profile: {
        id: stageForm.providerId.trim(),
        display_name: stageForm.displayName.trim(),
        backend_kind: stageForm.backendKind,
        api_mode: stageForm.apiMode,
        default_base_url: stageForm.baseUrl.trim(),
        auth_type: stageForm.authType,
        data_policy: stageForm.dataPolicy,
        capabilities,
        fallback_models: declaredModels,
      },
      hooks,
      replacement_target: stageForm.replacementTarget.trim() || null,
    };
    void runAction(async () => {
      const preview = await apiPost<PackagePreview>('/api/llm/provider-packages/stage', stageBody, { admin: true });
      const enriched: PackagePreview = {
        ...preview,
        lifecycle_status: 'staged',
        declared_models: declaredModels,
      };
      upsertPackage(enriched);
      syncFromPreview(enriched, declaredModels);
      return `Staged ${preview.provider_id} (${preview.artifact_id}); model selection unchanged`;
    });
  };

  const handlePropose = () => {
    const targetArtifact = proposeArtifactId.trim();
    if (!targetArtifact) return;
    void runAction(async () => {
      const result = await apiPost<ProposeResult>(`/api/llm/provider-packages/${encodeURIComponent(targetArtifact)}/propose`, {}, { admin: true });
      const enriched: PackagePreview = {
        ...result,
        proposal_id: result.proposal_id,
        lifecycle_status: result.status || 'pending',
      };
      upsertPackage(enriched);
      syncFromPreview(enriched);
      return `Proposal ${result.proposal_id} created (${result.status})`;
    });
  };

  const handleDecision = (approved: boolean) => {
    const targetProposal = decisionProposalId.trim();
    const targetArtifact = decisionArtifactId.trim();
    const targetHash = decisionHash.trim();
    if (!targetProposal || !targetArtifact || !targetHash || !permanentConsent) return;
    const decisionBody = {
      artifact_id: targetArtifact,
      package_hash: targetHash,
      approved,
      permanent: true as const,
    };
    void runAction(async () => {
      const result = await apiPost<DecisionResult>(`/api/llm/provider-packages/proposals/${encodeURIComponent(targetProposal)}/decision`, decisionBody, { admin: true });
      setPackages((prev) => {
        const existing = prev[targetArtifact];
        if (!existing) return prev;
        return {
          ...prev,
          [targetArtifact]: {
            ...existing,
            proposal_id: result.proposal_id,
            lifecycle_status: result.status,
          },
        };
      });
      return `Proposal ${result.proposal_id} marked ${result.status}`;
    }, { resetConsent: true });
  };

  const handlePromote = () => {
    const targetProposal = decisionProposalId.trim();
    if (!targetProposal) return;
    void runAction(async () => {
      const result = await apiPost<PromoteResult>(`/api/llm/provider-packages/proposals/${encodeURIComponent(targetProposal)}/promote`, {}, { admin: true });
      const enriched: PackagePreview = {
        ...result,
        proposal_id: targetProposal,
        lifecycle_status: result.status || 'active',
      };
      upsertPackage(enriched);
      syncFromPreview(enriched);
      return `Activated package ${result.provider_id} (${result.status}); model selection unchanged`;
    });
  };

  const handleRevoke = () => {
    const targetProvider = revokeProviderId.trim();
    if (!targetProvider) return;
    void runAction(async () => {
      const result = await apiPost<RevokeResult>(`/api/llm/provider-packages/${encodeURIComponent(targetProvider)}/revoke`, {}, { admin: true });
      setPackages((prev) => {
        const next = { ...prev };
        for (const [id, item] of Object.entries(next)) {
          if (item.provider_id === result.provider_id) {
            next[id] = { ...item, lifecycle_status: result.status || 'revoked' };
          }
        }
        return next;
      });
      return `Provider ${result.provider_id} ${result.status}`;
    }, { refreshSelection: true });
  };

  const handleCredentialCheck = () => {
    const provider = credProvider.trim();
    const hash = credHash.trim();
    if (!provider || !hash) return;
    void runAction(async () => {
      const result = await apiGet<CredentialStatus>(`/api/admin/llm/provider-credentials?provider=${encodeURIComponent(provider)}&package_hash=${encodeURIComponent(hash)}`, { admin: true });
      setCredStatus(result);
      return `Credential for ${provider}: ${result.configured ? 'configured' : 'absent'} (generation ${result.generation})`;
    });
  };

  const handleCredentialSave = () => {
    const provider = credProvider.trim();
    const hash = credHash.trim();
    const secretToSend = credSecret;
    if (!provider || !hash || !secretToSend) return;
    setCredSecret('');
    void runAction(async () => {
      const result = await apiPut<CredentialStatus>('/api/admin/llm/provider-credentials', {
        provider,
        package_hash: hash,
        value: secretToSend,
      }, { admin: true });
      setCredStatus(result);
      return `Credential stored for ${provider} (generation ${result.generation})`;
    }, { clearSecret: true, refreshSelection: true });
  };

  const handleCredentialDelete = () => {
    const provider = credProvider.trim();
    const hash = credHash.trim();
    if (!provider || !hash) return;
    setCredSecret('');
    void runAction(async () => {
      const result = await apiDeleteBody<CredentialStatus>('/api/admin/llm/provider-credentials', {
        provider,
        package_hash: hash,
      }, { admin: true });
      setCredStatus(result);
      return `Credential deleted for ${provider} (generation ${result.generation})`;
    }, { clearSecret: true, refreshSelection: true });
  };

  const handleSelectProvider = () => {
    const provider = selProvider.trim();
    const hash = selHash.trim();
    const model = selModel.trim();
    const rev = Number.parseInt(expectedRevision, 10);
    if (!provider || !hash || !model || Number.isNaN(rev) || rev < 0 || !ackUnknownPrice) return;
    const selectionBody = {
      provider,
      package_hash: hash,
      model,
      expected_revision: rev,
      acknowledge_unknown_price: ackUnknownPrice,
      acknowledge_data_policy: ackDataPolicy,
    };
    void runAction(async () => {
      const result = await apiPut<SelectionStatus>('/api/admin/llm/provider-selection', selectionBody, { admin: true });
      setSelection(result);
      setSelectionRefusal('');
      if (typeof result.revision === 'number') {
        setExpectedRevision(String(result.revision));
      }
      return `Selected ${result.provider} (${result.model}) at revision ${result.revision}`;
    }, { refreshSelection: true });
  };

  const handleClearSelection = () => {
    const rev = Number.parseInt(expectedRevision, 10);
    if (Number.isNaN(rev) || rev < 0) return;
    void runAction(async () => {
      const result = await apiDeleteBody<{ status: string; revision: number }>('/api/admin/llm/provider-selection', {
        expected_revision: rev,
      }, { admin: true });
      setExpectedRevision(String(result.revision));
      return `Provider selection cleared (revision ${result.revision})`;
    }, { refreshSelection: true });
  };

  const inventory = Object.values(packages);
  const selectedPkg = selectedArtifactId ? packages[selectedArtifactId] || null : null;
  const subSummary = pkgStatus
    ? `${pkgStatus.enabled ? 'plugins enabled' : 'plugins disabled'} · ${
      selection?.status === 'selected'
        ? `${selection.provider} (${selection.model})`
        : selection?.status || 'selection unavailable'
    }`
    : undefined;

  return (
    <Card
      title="SIGNED PROVIDER PACKAGES"
      live={asLive(pkgStatus, pkgStatus?.enabled)}
      sub={subSummary}
      onReload={() => { void reload(); }}
    >
      <p style={{ fontSize: 12, color: 'var(--ink-2)', margin: '0 0 8px' }}>
        Owner-governed signed provider packages, host-encrypted credentials, and revisioned model selection.
        Staging, approval, and promotion remain inert and never implicitly select a model.
      </p>

      {statusError && (
        <div role="alert" style={{ ...mono, color: 'var(--red)', marginBottom: 8 }}>
          {statusError}
        </div>
      )}

      {selectionRefusal && (
        <div role="alert" style={{ ...mono, color: 'var(--amber)', marginBottom: 8 }}>
          selection status · {selectionRefusal}
        </div>
      )}

      {banner && (
        <div
          role={banner.kind === 'error' ? 'alert' : 'status'}
          style={{
            ...mono,
            color: banner.kind === 'error' ? 'var(--red)' : 'var(--green)',
            border: `1px solid ${banner.kind === 'error' ? 'var(--red)' : 'var(--panel-line)'}`,
            borderRadius: 4,
            padding: '6px 8px',
            marginBottom: 8,
          }}
        >
          {banner.text}
        </div>
      )}

      {pkgStatus && (
        <Row>
          <span style={mono}>
            plugin gate: <strong>{pkgStatus.enabled ? 'enabled' : 'disabled'}</strong> ·
            runtime: {pkgStatus.runtime_present ? 'present' : 'absent'} ·
            selects_model: {String(pkgStatus.selects_model)}
          </span>
          <Tag c={pkgStatus.enabled ? 'var(--green)' : 'var(--amber)'}>
            {pkgStatus.enabled ? 'READY' : 'INERT'}
          </Tag>
        </Row>
      )}

      {/* 1. Package Inventory & Artifact Inspection */}
      <section aria-label="Package inventory" style={sectionBox}>
        <h4 style={{ ...mono, margin: 0 }}>Package inventory &amp; inspection</h4>
        <form onSubmit={handleInspect} style={{ display: 'flex', gap: 8, marginTop: 8, flexWrap: 'wrap' }}>
          <input
            aria-label="Inspect artifact ID"
            placeholder="32-char hex artifact_id"
            value={inspectInput}
            onChange={(e) => setInspectInput(e.target.value)}
            style={{ ...inpS, flex: '1 1 240px' }}
          />
          <button className="tool-btn" type="submit" disabled={busy || !inspectInput.trim()}>
            Inspect artifact
          </button>
        </form>

        {inventory.length === 0 ? (
          <p style={{ fontSize: 11.5, color: 'var(--ink-2)', margin: '8px 0 0' }}>
            No artifacts loaded in this session yet. Stage a signed candidate below or inspect an existing artifact ID.
          </p>
        ) : (
          <div style={{ marginTop: 8 }}>
            {inventory.map((item) => (
              <Row key={item.artifact_id}>
                <span style={mono}>
                  <strong>{item.provider_id}</strong> · {item.artifact_id.slice(0, 12)}… · {item.endpoint_host}
                </span>
                <Tag>{item.lifecycle_status || 'staged'}</Tag>
                <Tag>{item.backend_kind}</Tag>
                <button
                  type="button"
                  className="tool-btn"
                  style={{ marginLeft: 'auto' }}
                  onClick={() => syncFromPreview(item)}
                >
                  Inspect view
                </button>
              </Row>
            ))}
          </div>
        )}

        {selectedPkg && (
          <div
            aria-label="Selected package detail"
            style={{
              marginTop: 10,
              padding: 8,
              background: 'var(--surface)',
              border: '1px solid var(--panel-line)',
              borderRadius: 4,
              ...mono,
            }}
          >
            <div>
              <strong>{selectedPkg.provider_id}</strong> · status:{' '}
              <span>{selectedPkg.lifecycle_status || 'staged'}</span>
              {selectedPkg.proposal_id ? ` · proposal: ${selectedPkg.proposal_id}` : ''}
            </div>
            <div>artifact_id: {selectedPkg.artifact_id}</div>
            <div>package_hash: {selectedPkg.package_hash}</div>
            <div>
              source: {selectedPkg.source} · host: {selectedPkg.endpoint_host} · backend: {selectedPkg.backend_kind} ·
              mode: {selectedPkg.profile_summary?.api_mode || 'chat_completions'} · auth: {selectedPkg.auth_type}
            </div>
            <div>
              policy: {selectedPkg.profile_summary?.data_policy?.policy || 'unknown'} ·
              hooks: {(selectedPkg.hooks || []).join(', ')} ·
              members: {selectedPkg.member_count} ({selectedPkg.member_bytes} B) ·
              sandbox: {selectedPkg.sandbox_image}
            </div>
            {selectedPkg.replacement_target && (
              <div>replacement_target: {selectedPkg.replacement_target}</div>
            )}
          </div>
        )}
      </section>

      {/* 2. Stage Signed Candidate */}
      <form onSubmit={handleStage} aria-label="Stage signed package" style={sectionBox}>
        <h4 style={{ ...mono, margin: 0 }}>Stage signed candidate</h4>
        <div style={fieldGrid}>
          <label style={labelStyle}>
            Candidate ref
            <input
              aria-label="Candidate ref"
              value={stageForm.candidate}
              onChange={(e) => setStageForm({ ...stageForm, candidate: e.target.value })}
              style={inpS}
              required
            />
          </label>
          <label style={labelStyle}>
            Source
            <select
              aria-label="Package source"
              value={stageForm.source}
              onChange={(e) => setStageForm({ ...stageForm, source: e.target.value as 'user' | 'legacy' | 'bundled' })}
              style={inpS}
            >
              <option value="user">user</option>
              <option value="legacy">legacy</option>
              <option value="bundled">bundled</option>
            </select>
          </label>
          <label style={labelStyle}>
            Provider ID
            <input
              aria-label="Stage provider ID"
              value={stageForm.providerId}
              onChange={(e) => setStageForm({ ...stageForm, providerId: e.target.value })}
              placeholder="synthetic-addon"
              style={inpS}
              required
            />
          </label>
          <label style={labelStyle}>
            Display name
            <input
              aria-label="Stage display name"
              value={stageForm.displayName}
              onChange={(e) => setStageForm({ ...stageForm, displayName: e.target.value })}
              placeholder="Synthetic Addon"
              style={inpS}
              required
            />
          </label>
          <label style={labelStyle}>
            Default base URL
            <input
              aria-label="Stage base URL"
              value={stageForm.baseUrl}
              onChange={(e) => setStageForm({ ...stageForm, baseUrl: e.target.value })}
              placeholder="https://api.example.org/v1"
              style={inpS}
              required
            />
          </label>
          <label style={labelStyle}>
            Backend kind
            <select
              aria-label="Stage backend kind"
              value={stageForm.backendKind}
              onChange={(e) => setStageForm({ ...stageForm, backendKind: e.target.value })}
              style={inpS}
            >
              {BACKEND_KINDS.map((kind) => (
                <option key={kind} value={kind}>{kind}</option>
              ))}
            </select>
          </label>
          <label style={labelStyle}>
            API mode
            <select
              aria-label="Stage API mode"
              value={stageForm.apiMode}
              onChange={(e) => setStageForm({ ...stageForm, apiMode: e.target.value })}
              style={inpS}
            >
              {API_MODES.map((mode) => (
                <option key={mode} value={mode}>{mode}</option>
              ))}
            </select>
          </label>
          <label style={labelStyle}>
            Auth type
            <select
              aria-label="Stage auth type"
              value={stageForm.authType}
              onChange={(e) => setStageForm({ ...stageForm, authType: e.target.value })}
              style={inpS}
            >
              <option value="bearer">bearer</option>
              <option value="api-key">api-key</option>
              <option value="none">none</option>
            </select>
          </label>
          <label style={labelStyle}>
            Data policy
            <select
              aria-label="Stage data policy"
              value={stageForm.dataPolicy}
              onChange={(e) => setStageForm({ ...stageForm, dataPolicy: e.target.value })}
              style={inpS}
            >
              <option value="unknown">unknown</option>
              <option value="no-training">no-training</option>
              <option value="trains-on-inputs">trains-on-inputs</option>
              <option value="local">local</option>
            </select>
          </label>
          <label style={labelStyle}>
            Capabilities (comma-separated)
            <input
              aria-label="Stage capabilities"
              value={stageForm.capabilities}
              onChange={(e) => setStageForm({ ...stageForm, capabilities: e.target.value })}
              style={inpS}
            />
          </label>
          <label style={labelStyle}>
            Declared models (comma-separated)
            <input
              aria-label="Stage declared models"
              value={stageForm.models}
              onChange={(e) => setStageForm({ ...stageForm, models: e.target.value })}
              placeholder="addon-chat"
              style={inpS}
            />
          </label>
          <label style={labelStyle}>
            Hooks (comma-separated)
            <input
              aria-label="Stage hooks"
              value={stageForm.hooks}
              onChange={(e) => setStageForm({ ...stageForm, hooks: e.target.value })}
              style={inpS}
              required
            />
          </label>
          <label style={labelStyle}>
            Replacement target (optional)
            <input
              aria-label="Stage replacement target"
              value={stageForm.replacementTarget}
              onChange={(e) => setStageForm({ ...stageForm, replacementTarget: e.target.value })}
              style={inpS}
            />
          </label>
        </div>
        <div style={{ marginTop: 8 }}>
          <button className="tool-btn" type="submit" disabled={busy}>
            Stage candidate
          </button>
        </div>
      </form>

      {/* 3. Admission Lifecycle: Propose, Permanent Owner Decision, Promote, Revoke */}
      <section aria-label="Package admission lifecycle" style={sectionBox}>
        <h4 style={{ ...mono, margin: 0 }}>Admission lifecycle (propose · decide · promote · revoke)</h4>
        <div style={fieldGrid}>
          <label style={labelStyle}>
            Artifact ID to propose
            <input
              aria-label="Proposal artifact ID"
              value={proposeArtifactId}
              onChange={(e) => {
                setProposeArtifactId(e.target.value);
                setDecisionArtifactId(e.target.value);
              }}
              placeholder="32-char hex"
              style={inpS}
            />
          </label>
          <label style={labelStyle}>
            Proposal ID
            <input
              aria-label="Decision proposal ID"
              value={decisionProposalId}
              onChange={(e) => setDecisionProposalId(e.target.value)}
              placeholder="proposal id"
              style={inpS}
            />
          </label>
          <label style={labelStyle}>
            Decision package hash
            <input
              aria-label="Decision package hash"
              value={decisionHash}
              onChange={(e) => setDecisionHash(e.target.value)}
              placeholder="64-char sha256 hex"
              style={inpS}
            />
          </label>
          <label style={labelStyle}>
            Active provider ID to revoke
            <input
              aria-label="Revoke provider ID"
              value={revokeProviderId}
              onChange={(e) => setRevokeProviderId(e.target.value)}
              placeholder="provider id"
              style={inpS}
            />
          </label>
        </div>

        <label style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 8, fontSize: 11.5, color: 'var(--ink-2)' }}>
          <input
            type="checkbox"
            checked={permanentConsent}
            onChange={(e) => setPermanentConsent(e.target.checked)}
          />
          I permanently authorize this exact artifact and package hash decision
        </label>

        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 8 }}>
          <button
            type="button"
            className="tool-btn"
            disabled={busy || !proposeArtifactId.trim()}
            onClick={handlePropose}
          >
            Propose artifact
          </button>
          <button
            type="button"
            className="tool-btn"
            disabled={busy || !permanentConsent || !decisionProposalId.trim() || !decisionArtifactId.trim() || !decisionHash.trim()}
            onClick={() => handleDecision(true)}
          >
            Approve proposal
          </button>
          <button
            type="button"
            className="tool-btn"
            disabled={busy || !permanentConsent || !decisionProposalId.trim() || !decisionArtifactId.trim() || !decisionHash.trim()}
            onClick={() => handleDecision(false)}
          >
            Deny proposal
          </button>
          <button
            type="button"
            className="tool-btn"
            disabled={busy || !decisionProposalId.trim()}
            onClick={handlePromote}
          >
            Promote (activate package)
          </button>
          <button
            type="button"
            className="tool-btn"
            disabled={busy || !revokeProviderId.trim()}
            onClick={handleRevoke}
          >
            Revoke (deactivate / remove)
          </button>
        </div>
      </section>

      {/* 4. Host-Owned Encrypted Credentials */}
      <section aria-label="Provider credentials" style={sectionBox}>
        <h4 style={{ ...mono, margin: 0 }}>Host-encrypted provider credentials</h4>
        {credStatus && (
          <p style={{ ...mono, margin: '6px 0 0', color: 'var(--ink-2)' }}>
            credential status: {credStatus.configured ? 'configured' : 'absent'} · generation {credStatus.generation}
          </p>
        )}
        <div style={fieldGrid}>
          <label style={labelStyle}>
            Credential provider ID
            <input
              aria-label="Credential provider ID"
              value={credProvider}
              onChange={(e) => setCredProvider(e.target.value)}
              placeholder="provider id"
              style={inpS}
            />
          </label>
          <label style={labelStyle}>
            Credential package hash
            <input
              aria-label="Credential package hash"
              value={credHash}
              onChange={(e) => setCredHash(e.target.value)}
              placeholder="64-char sha256 hex"
              style={inpS}
            />
          </label>
          <label style={labelStyle}>
            Secret (never shown after submit)
            <input
              aria-label="Provider credential secret"
              type="password"
              autoComplete="off"
              value={credSecret}
              onChange={(e) => setCredSecret(e.target.value)}
              style={inpS}
            />
          </label>
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 8 }}>
          <button
            type="button"
            className="tool-btn"
            disabled={busy || !credProvider.trim() || !credHash.trim()}
            onClick={handleCredentialCheck}
          >
            Check credential
          </button>
          <button
            type="button"
            className="tool-btn"
            disabled={busy || !credProvider.trim() || !credHash.trim() || !credSecret}
            onClick={handleCredentialSave}
          >
            Store or rotate credential
          </button>
          <button
            type="button"
            className="tool-btn"
            disabled={busy || !credProvider.trim() || !credHash.trim()}
            onClick={handleCredentialDelete}
          >
            Delete credential
          </button>
        </div>
      </section>

      {/* 5. Revisioned Provider Selection */}
      <section aria-label="Provider selection" style={sectionBox}>
        <h4 style={{ ...mono, margin: 0 }}>Revisioned provider model selection</h4>
        {selection && (
          <p style={{ ...mono, margin: '6px 0 0', color: 'var(--ink-2)' }}>
            current selection: <strong>{selection.status}</strong>
            {selection.provider ? ` · ${selection.provider} (${selection.model})` : ''}
            {typeof selection.revision === 'number' ? ` · revision ${selection.revision}` : ''}
            {typeof selection.credential_generation === 'number'
              ? ` · credential generation ${selection.credential_generation}`
              : ''}
          </p>
        )}
        <div style={fieldGrid}>
          <label style={labelStyle}>
            Selected provider ID
            <input
              aria-label="Selection provider ID"
              value={selProvider}
              onChange={(e) => setSelProvider(e.target.value)}
              placeholder="provider id"
              style={inpS}
            />
          </label>
          <label style={labelStyle}>
            Selected package hash
            <input
              aria-label="Selection package hash"
              value={selHash}
              onChange={(e) => setSelHash(e.target.value)}
              placeholder="64-char sha256 hex"
              style={inpS}
            />
          </label>
          <label style={labelStyle}>
            Declared model
            <input
              aria-label="Selection model"
              value={selModel}
              onChange={(e) => setSelModel(e.target.value)}
              placeholder="declared model id"
              style={inpS}
            />
          </label>
          <label style={labelStyle}>
            Expected revision
            <input
              aria-label="Selection expected revision"
              type="number"
              min={0}
              value={expectedRevision}
              onChange={(e) => setExpectedRevision(e.target.value)}
              style={inpS}
            />
          </label>
        </div>

        <label style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 8, fontSize: 11.5, color: 'var(--ink-2)' }}>
          <input
            type="checkbox"
            checked={ackUnknownPrice}
            onChange={(e) => setAckUnknownPrice(e.target.checked)}
          />
          I acknowledge unknown model price
        </label>
        <label style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 4, fontSize: 11.5, color: 'var(--ink-2)' }}>
          <input
            type="checkbox"
            checked={ackDataPolicy}
            onChange={(e) => setAckDataPolicy(e.target.checked)}
          />
          I acknowledge the selected data policy
        </label>

        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 8 }}>
          <button
            type="button"
            className="tool-btn"
            disabled={busy || !ackUnknownPrice || !selProvider.trim() || !selHash.trim() || !selModel.trim()}
            onClick={handleSelectProvider}
          >
            Select provider model
          </button>
          <button
            type="button"
            className="tool-btn"
            disabled={busy}
            onClick={handleClearSelection}
          >
            Clear selection
          </button>
        </div>
      </section>
    </Card>
  );
}
