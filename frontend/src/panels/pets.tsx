import React, { useCallback, useEffect, useState } from 'react';
import { apiDelete, apiGet, apiPost, apiPut } from '../api/client';
import { Card } from '../panel-kit';

export type AgentPetState = 'idle' | 'thinking' | 'tool' | 'finishing' | 'failing';

type PetMeta = {
  id: string;
  name: string;
  species: string;
  rarity: string;
  vibe: string;
  builtin: boolean;
  palette: Record<string, string>;
  states: string[];
  thumb_svg?: string;
  active?: boolean;
};

type PetInfo = {
  ok: boolean;
  enabled: boolean;
  active_id: string;
  active_pet: PetMeta;
  scale: number;
  roam: boolean;
  overlay_enabled: boolean;
  image_backend: string;
  installed_count: number;
  custom_count: number;
  example_prompts: string[];
  image_backends: string[];
  agent_states: AgentPetState[];
  agent_state: AgentPetState;
  detail: string;
  vibe_reaction: string;
  current_cells: string[][];
};

type PetGallery = {
  ok: boolean;
  active_id: string;
  enabled: boolean;
  pets: PetMeta[];
};

type HatchDraft = {
  draft_id: string;
  index: number;
  vibe: string;
  rarity: string;
  palette: Record<string, string>;
  preview_cells: string[][];
};

type HatchJob = {
  ok: boolean;
  job_id: string;
  prompt: string;
  image_backend: string;
  has_reference_image: boolean;
  reference_tint?: string | null;
  status: string;
  drafts: HatchDraft[];
  hatched_pet_id?: string | null;
};

type DoctorReport = {
  ok: boolean;
  active_id: string;
  terminal_protocol: string;
  checks: Array<{ name: string; ok: boolean; detail: string }>;
};

const HEX_RE = /^#[0-9a-fA-F]{6}$/;

function safeColor(c: unknown): string {
  return typeof c === 'string' && HEX_RE.test(c) ? c : '#0d1b2a';
}

export function SpriteGrid({
  cells,
  pixelSize = 6,
  label,
}: {
  cells?: string[][];
  pixelSize?: number;
  label?: string;
}) {
  if (!Array.isArray(cells) || cells.length === 0) return null;
  const rows = cells.length;
  const cols = Array.isArray(cells[0]) ? cells[0].length : 0;
  if (!cols) return null;
  return (
    <div
      role="img"
      aria-label={label || 'companion sprite'}
      style={{
        display: 'inline-grid',
        gridTemplateColumns: `repeat(${cols}, ${pixelSize}px)`,
        gridTemplateRows: `repeat(${rows}, ${pixelSize}px)`,
        border: '1px solid var(--panel-line)',
        borderRadius: 4,
        overflow: 'hidden',
        flexShrink: 0,
      }}
    >
      {cells.flatMap((row, y) =>
        row.map((cell, x) => (
          <span
            key={`${y}-${x}`}
            style={{
              width: pixelSize,
              height: pixelSize,
              backgroundColor: safeColor(cell),
              display: 'block',
            }}
          />
        )),
      )}
    </div>
  );
}

function notifyPetsChanged() {
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent('nerva:pets-updated'));
  }
}

export function PetCompanionOverlay({
  enabled = true,
  agentState = 'idle',
  standalone = false,
}: {
  enabled?: boolean;
  agentState?: AgentPetState;
  standalone?: boolean;
}) {
  const [info, setInfo] = useState<PetInfo | null>(null);
  const [frameCells, setFrameCells] = useState<string[][] | null>(null);
  const [frameTick, setFrameTick] = useState(0);
  const [roamOffset, setRoamOffset] = useState(0);

  const load = useCallback(() => {
    if (!enabled) return;
    const stateQ = encodeURIComponent(agentState || 'idle');
    apiGet<PetInfo>(`/api/pets?state=${stateQ}`)
      .then((res) => {
        if (res && res.ok === true && Array.isArray(res.current_cells)) {
          setInfo(res);
          setFrameCells(res.current_cells);
        } else {
          setInfo(null);
        }
      })
      .catch(() => {
        setInfo(null);
      });
  }, [enabled, agentState]);

  useEffect(() => {
    if (!enabled) return undefined;
    load();
    const onUpdated = () => load();
    window.addEventListener('nerva:pets-updated', onUpdated);
    const pollIv = setInterval(load, 15000);
    return () => {
      window.removeEventListener('nerva:pets-updated', onUpdated);
      clearInterval(pollIv);
    };
  }, [enabled, load]);

  const showOverlay =
    enabled &&
    info?.ok === true &&
    info.enabled === true &&
    (standalone || info.overlay_enabled === true);

  useEffect(() => {
    if (!showOverlay || !info?.active_id) return undefined;
    const animIv = setInterval(() => {
      setFrameTick((prev) => {
        const next = (prev + 1) % 2;
        const pid = info.active_id;
        const st = agentState || info.agent_state || 'idle';
        apiGet<any>(`/api/pets/${encodeURIComponent(pid)}/cells?state=${encodeURIComponent(st)}&frame=${next}`)
          .then((res) => {
            if (Array.isArray(res?.cells)) setFrameCells(res.cells);
          })
          .catch(() => {});
        return next;
      });
      if (info.roam) {
        setRoamOffset((prev) => (prev + 18) % 144);
      } else {
        setRoamOffset(0);
      }
    }, 2400);
    return () => clearInterval(animIv);
  }, [showOverlay, info?.active_id, info?.roam, info?.agent_state, agentState]);

  if (!showOverlay || !info) return null;

  const scale = Math.max(0.5, Math.min(3, Number(info.scale) || 1));
  const px = Math.max(4, Math.round(6 * scale));

  return (
    <div
      data-testid="pet-companion-overlay"
      data-frame={frameTick}
      style={{
        position: standalone ? 'relative' : 'fixed',
        right: standalone ? undefined : 18 + roamOffset,
        bottom: standalone ? undefined : 58,
        zIndex: 9999,
        display: 'inline-flex',
        alignItems: 'center',
        gap: 8,
        padding: '6px 10px',
        borderRadius: 8,
        background: 'rgba(10, 16, 28, 0.92)',
        border: '1px solid var(--panel-line)',
        boxShadow: '0 6px 20px rgba(0,0,0,0.45)',
        transition: 'right 0.6s ease',
        pointerEvents: 'auto',
      }}
    >
      <SpriteGrid
        cells={frameCells || info.current_cells}
        pixelSize={px}
        label={`${info.active_pet?.name || info.active_id} (${agentState})`}
      />
      <div style={{ fontSize: 10.5, lineHeight: 1.35 }}>
        <div style={{ fontWeight: 700, color: 'var(--ink)' }}>
          {info.active_pet?.name || info.active_id}{' '}
          <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--accent-light)' }}>
            [{agentState}]
          </span>
        </div>
        <div style={{ color: 'var(--ink-2)' }}>{info.vibe_reaction}</div>
      </div>
    </div>
  );
}

export function PetsPanel() {
  const [info, setInfo] = useState<PetInfo | null>(null);
  const [gallery, setGallery] = useState<PetMeta[]>([]);
  const [doctor, setDoctor] = useState<DoctorReport | null>(null);
  const [previewState, setPreviewState] = useState<AgentPetState>('idle');
  const [inspectDetail, setInspectDetail] = useState('');
  const [thumbUri, setThumbUri] = useState('');
  const [renameValues, setRenameValues] = useState<Record<string, string>>({});
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [importB64, setImportB64] = useState('');
  const [exportNote, setExportNote] = useState('');

  // Hatch-a-Pet studio state
  const [conceptPrompt, setConceptPrompt] = useState('cybernetic barn owl with glowing amber runes');
  const [backendChoice, setBackendChoice] = useState('procedural-pixel');
  const [refImageB64, setRefImageB64] = useState('');
  const [activeJob, setActiveJob] = useState<HatchJob | null>(null);
  const [remixInstruction, setRemixInstruction] = useState('brighter eyes and starlight crest');
  const [confirmRemix, setConfirmRemix] = useState(false);
  const [adoptName, setAdoptName] = useState('');
  const [statusNote, setStatusNote] = useState('');

  const refresh = useCallback(() => {
    apiGet<PetInfo>('/api/pets')
      .then((res) => {
        setInfo(res);
        if (res?.image_backend) setBackendChoice(res.image_backend);
      })
      .catch(() => setInfo(null));
    apiGet<PetGallery>('/api/pets/gallery')
      .then((res) => setGallery(Array.isArray(res?.pets) ? res.pets : []))
      .catch(() => setGallery([]));
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const updatePrefs = async (patch: Record<string, unknown>, label: string) => {
    try {
      const res = await apiPut<PetInfo>('/api/pets/preferences', patch, { admin: true });
      setInfo(res);
      setStatusNote(label);
      notifyPetsChanged();
      refresh();
    } catch (err: any) {
      setStatusNote(String(err?.message || 'preference update failed'));
    }
  };

  const selectPet = async (pid: string) => {
    try {
      await apiPost('/api/pets/select', { pet_id: pid }, { admin: true });
      setStatusNote(`selected ${pid}`);
      notifyPetsChanged();
      refresh();
    } catch (err: any) {
      setStatusNote(String(err?.message || 'select failed'));
    }
  };

  const inspectPet = async (pid: string, st: AgentPetState = previewState) => {
    try {
      const metaRes = await apiGet<any>(`/api/pets/${encodeURIComponent(pid)}/meta`);
      const cellsRes = await apiGet<any>(`/api/pets/${encodeURIComponent(pid)}/cells?state=${encodeURIComponent(st)}`);
      const thumbRes = await apiGet<any>(`/api/pets/${encodeURIComponent(pid)}/thumb?state=${encodeURIComponent(st)}`);
      setThumbUri(String(thumbRes?.data_uri || ''));
      setInspectDetail(
        JSON.stringify(
          {
            meta: metaRes?.pet,
            state: cellsRes?.state,
            rows: cellsRes?.rows,
            cols: cellsRes?.cols,
            frame_count: cellsRes?.frame_count,
          },
          null,
          2,
        ),
      );
      if (Array.isArray(cellsRes?.cells) && info) {
        setInfo({ ...info, current_cells: cellsRes.cells, agent_state: st });
      }
    } catch (err: any) {
      setStatusNote(String(err?.message || 'inspect failed'));
    }
  };

  const renamePet = async (pid: string) => {
    const cleanName = (renameValues[pid] || '').trim();
    if (!cleanName) return;
    try {
      await apiPost(`/api/pets/${encodeURIComponent(pid)}/rename`, { name: cleanName }, { admin: true });
      setRenameValues((prev) => ({ ...prev, [pid]: '' }));
      setStatusNote(`renamed ${pid} -> ${cleanName}`);
      notifyPetsChanged();
      refresh();
    } catch (err: any) {
      setStatusNote(String(err?.message || 'rename failed'));
    }
  };

  const deleteCustomPet = async (pid: string) => {
    try {
      await apiDelete(`/api/pets/${encodeURIComponent(pid)}?confirm=true`, { admin: true });
      setConfirmDeleteId(null);
      setStatusNote(`deleted custom companion ${pid}`);
      notifyPetsChanged();
      refresh();
    } catch (err: any) {
      setStatusNote(String(err?.message || 'delete failed'));
    }
  };

  const exportPetZip = async (pid: string) => {
    try {
      const res = await apiGet<any>(`/api/pets/${encodeURIComponent(pid)}/export`);
      if (res?.zip_base64) {
        setImportB64(res.zip_base64);
        setExportNote(`exported ${res.filename} (${res.size_bytes} B) — base64 staged below`);
      }
    } catch (err: any) {
      setStatusNote(String(err?.message || 'export failed'));
    }
  };

  const importPetZip = async () => {
    if (!importB64.trim()) return;
    try {
      const res = await apiPost<any>('/api/pets/import', { zip_base64: importB64.trim() }, { admin: true });
      setStatusNote(`imported ${res?.pet?.name || res?.pet?.id || 'companion'}`);
      setImportB64('');
      refresh();
    } catch (err: any) {
      setStatusNote(String(err?.message || 'import failed'));
    }
  };

  const runDoctor = async () => {
    try {
      const res = await apiGet<DoctorReport>('/api/pets/doctor');
      setDoctor(res);
      setStatusNote(`doctor: ${res.ok ? 'all checks healthy' : 'attention required'} (${res.terminal_protocol})`);
    } catch (err: any) {
      setStatusNote(String(err?.message || 'doctor failed'));
    }
  };

  const onRefFile = (ev: React.ChangeEvent<HTMLInputElement>) => {
    const file = ev.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      if (typeof reader.result === 'string') {
        setRefImageB64(reader.result);
      }
    };
    reader.readAsDataURL(file);
  };

  const generateDrafts = async () => {
    if (!conceptPrompt.trim()) return;
    try {
      const res = await apiPost<HatchJob>(
        '/api/pets/hatch/generate',
        {
          prompt: conceptPrompt.trim(),
          image_backend: backendChoice,
          reference_image_b64: refImageB64,
        },
        { admin: true },
      );
      setActiveJob(res);
      setStatusNote(`generated ${res.drafts?.length || 0} candidate drafts (${res.job_id})`);
    } catch (err: any) {
      setStatusNote(String(err?.message || 'draft generation failed'));
    }
  };

  const pollJobStatus = async (jobId: string) => {
    try {
      const res = await apiGet<HatchJob>(`/api/pets/hatch/jobs/${encodeURIComponent(jobId)}`);
      setActiveJob(res);
      setStatusNote(`job ${res.job_id}: ${res.status}`);
    } catch (err: any) {
      setStatusNote(String(err?.message || 'job status check failed'));
    }
  };

  const cancelJob = async (jobId: string) => {
    try {
      const res = await apiPost<HatchJob>(`/api/pets/hatch/jobs/${encodeURIComponent(jobId)}/cancel`, {}, { admin: true });
      setActiveJob(res);
      setStatusNote(`cancelled ${jobId}`);
    } catch (err: any) {
      setStatusNote(String(err?.message || 'cancel failed'));
    }
  };

  const remixDraft = async (jobId: string, draftId: string) => {
    if (!confirmRemix) {
      setStatusNote('check Confirm remix before remixing candidate drafts');
      return;
    }
    try {
      const res = await apiPost<HatchJob>(
        `/api/pets/hatch/jobs/${encodeURIComponent(jobId)}/remix`,
        {
          draft_id: draftId,
          instruction: remixInstruction.trim(),
          confirm: true,
        },
        { admin: true },
      );
      setActiveJob(res);
      setStatusNote(`remixed candidate in ${jobId}`);
    } catch (err: any) {
      setStatusNote(String(err?.message || 'remix failed'));
    }
  };

  const adoptDraft = async (jobId: string, draftId: string) => {
    try {
      const res = await apiPost<any>(
        `/api/pets/hatch/jobs/${encodeURIComponent(jobId)}/adopt`,
        {
          draft_id: draftId,
          name: adoptName.trim(),
          adopt_active: true,
        },
        { admin: true },
      );
      setAdoptName('');
      setStatusNote(`hatched & adopted ${res?.pet?.name || res?.pet?.id}!`);
      await pollJobStatus(jobId);
      notifyPetsChanged();
      refresh();
    } catch (err: any) {
      setStatusNote(String(err?.message || 'adopt failed'));
    }
  };

  const openPopoutWindow = () => {
    if (typeof window !== 'undefined') {
      window.open('/v2/?pet_overlay=1', 'nerva-pet-companion', 'width=320,height=160,noopener');
    }
  };

  const scale = Number(info?.scale || 1);
  const examples = info?.example_prompts || [
    'cybernetic barn owl with glowing amber runes',
    'clockwork red panda carrying a tiny wrench',
  ];
  const backends = info?.image_backends || ['procedural-pixel', 'svg-synth', 'local-vlm'];

  return (
    <Card
      title="COMPANIONS · Petdex, Hatch-a-Pet & reactive overlay"
      sub={gallery.length}
      onReload={refresh}
    >
      {/* Active companion & live agent-state controls */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 12,
          padding: 10,
          border: '1px solid var(--panel-line)',
          borderRadius: 6,
          marginBottom: 12,
          flexWrap: 'wrap',
        }}
      >
        <SpriteGrid
          cells={info?.current_cells}
          pixelSize={Math.max(5, Math.round(7 * scale))}
          label={info?.active_pet?.name || 'active companion'}
        />
        <div style={{ flex: 1, minWidth: 180, fontSize: 11 }}>
          <div style={{ fontWeight: 700, fontSize: 12.5 }}>
            {info?.active_pet?.name || 'Spark Owl'}{' '}
            <span style={{ color: 'var(--ink-2)', fontWeight: 400 }}>
              ({info?.active_pet?.species || 'Strigiformes Arc'})
            </span>
          </div>
          <div style={{ color: 'var(--accent-light)', marginTop: 2 }}>
            state: <code>{info?.agent_state || previewState}</code> · {info?.vibe_reaction || 'perched quietly'}
          </div>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 8 }}>
            <button
              className="tool-btn"
              onClick={() => updatePrefs({ enabled: !info?.enabled }, info?.enabled ? 'companion disabled' : 'companion enabled')}
            >
              {info?.enabled ? 'enabled ✓' : 'disabled'}
            </button>
            <button
              className="tool-btn"
              onClick={() =>
                updatePrefs(
                  { overlay_enabled: !info?.overlay_enabled },
                  info?.overlay_enabled ? 'HUD overlay hidden' : 'HUD overlay active',
                )
              }
            >
              {info?.overlay_enabled ? 'overlay on ✓' : 'overlay off'}
            </button>
            <button
              className="tool-btn"
              onClick={() => updatePrefs({ roam: !info?.roam }, info?.roam ? 'roaming paused' : 'roaming enabled')}
            >
              {info?.roam ? 'roam on ✓' : 'roam off'}
            </button>
            <button className="tool-btn" onClick={openPopoutWindow}>
              pop-out window
            </button>
            <button className="tool-btn" onClick={runDoctor}>
              run doctor
            </button>
          </div>
        </div>

        <div style={{ display: 'grid', gap: 4, fontSize: 10.5 }}>
          <label>
            scale ({scale.toFixed(1)}x)
            <input
              aria-label="Companion scale"
              type="range"
              min="0.5"
              max="3.0"
              step="0.25"
              value={scale}
              onChange={(ev) => updatePrefs({ scale: Number(ev.target.value) }, `scale ${ev.target.value}x`)}
              style={{ display: 'block', width: 110 }}
            />
          </label>
          <label>
            preview state
            <select
              aria-label="Preview agent state"
              value={previewState}
              onChange={(ev) => {
                const st = ev.target.value as AgentPetState;
                setPreviewState(st);
                if (info?.active_id) void inspectPet(info.active_id, st);
              }}
              style={{ display: 'block', width: 110 }}
            >
              {(['idle', 'thinking', 'tool', 'finishing', 'failing'] as AgentPetState[]).map((st) => (
                <option key={st} value={st}>
                  {st}
                </option>
              ))}
            </select>
          </label>
        </div>
      </div>

      {/* Hatch-a-Pet Studio */}
      <div
        style={{
          padding: 10,
          border: '1px solid var(--panel-line)',
          borderRadius: 6,
          marginBottom: 12,
        }}
      >
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--ink-2)', marginBottom: 6 }}>
          HATCH-A-PET · concept prompt, candidate grid, confirmed remix & adoption
        </div>
        <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginBottom: 6 }}>
          {examples.map((ex) => (
            <button key={ex} className="tool-btn" style={{ fontSize: 10 }} onClick={() => setConceptPrompt(ex)}>
              {ex.slice(0, 32)}…
            </button>
          ))}
        </div>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 8 }}>
          <input
            aria-label="Hatch concept prompt"
            value={conceptPrompt}
            onChange={(ev) => setConceptPrompt(ev.target.value)}
            placeholder="describe your companion concept..."
            style={{ flex: 1, minWidth: 180, padding: '4px 6px' }}
          />
          <select
            aria-label="Hatch image backend"
            value={backendChoice}
            onChange={(ev) => setBackendChoice(ev.target.value)}
          >
            {backends.map((b) => (
              <option key={b} value={b}>
                {b}
              </option>
            ))}
          </select>
          <input aria-label="Reference image" type="file" accept="image/*" onChange={onRefFile} style={{ width: 150, fontSize: 10 }} />
          <button className="tool-btn" onClick={generateDrafts}>
            generate 4 looks
          </button>
        </div>

        {activeJob && (
          <div style={{ marginTop: 8 }}>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 11, marginBottom: 6 }}>
              <code>{activeJob.job_id}</code>
              <span>status: <strong>{activeJob.status}</strong></span>
              <button className="tool-btn" onClick={() => pollJobStatus(activeJob.job_id)}>
                refresh status
              </button>
              {activeJob.status !== 'hatched' && activeJob.status !== 'cancelled' && (
                <button className="tool-btn" onClick={() => cancelJob(activeJob.job_id)}>
                  cancel job
                </button>
              )}
            </div>

            <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', marginBottom: 8, fontSize: 11 }}>
              <input
                aria-label="Hatchling name"
                value={adoptName}
                onChange={(ev) => setAdoptName(ev.target.value)}
                placeholder="optional hatchling name"
                style={{ padding: '3px 6px' }}
              />
              <input
                aria-label="Remix instruction"
                value={remixInstruction}
                onChange={(ev) => setRemixInstruction(ev.target.value)}
                placeholder="remix instruction"
                style={{ padding: '3px 6px', flex: 1 }}
              />
              <label style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                <input
                  type="checkbox"
                  checked={confirmRemix}
                  onChange={(ev) => setConfirmRemix(ev.target.checked)}
                />
                Confirm remix
              </label>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 8 }}>
              {(activeJob.drafts || []).map((d) => (
                <div
                  key={d.draft_id}
                  style={{
                    padding: 8,
                    border: '1px solid var(--panel-line)',
                    borderRadius: 6,
                    fontSize: 10.5,
                    display: 'grid',
                    gap: 6,
                  }}
                >
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                    <SpriteGrid cells={d.preview_cells} pixelSize={5} label={d.draft_id} />
                    <div>
                      <div style={{ fontWeight: 700 }}>{d.vibe}</div>
                      <div style={{ color: 'var(--ink-2)' }}>{d.rarity}</div>
                    </div>
                  </div>
                  {activeJob.status !== 'cancelled' && (
                    <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                      <button className="tool-btn" onClick={() => remixDraft(activeJob.job_id, d.draft_id)}>
                        remix
                      </button>
                      <button className="tool-btn" onClick={() => adoptDraft(activeJob.job_id, d.draft_id)}>
                        hatch & adopt
                      </button>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Petdex Gallery */}
      <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--ink-2)', marginBottom: 6 }}>
        PETDEX GALLERY ({gallery.length})
      </div>
      <div style={{ display: 'grid', gap: 6, marginBottom: 10 }}>
        {gallery.map((pet) => (
          <div
            key={pet.id}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              padding: '6px 8px',
              borderBottom: '1px solid var(--panel-line)',
              fontSize: 11,
              flexWrap: 'wrap',
            }}
          >
            <strong>{pet.name}</strong>
            <span style={{ color: 'var(--ink-2)' }}>
              ({pet.id} · {pet.rarity} · {pet.vibe})
            </span>
            {pet.active && <span style={{ color: 'var(--green)', fontFamily: 'var(--font-mono)' }}>ACTIVE</span>}
            <div style={{ marginLeft: 'auto', display: 'flex', gap: 4, alignItems: 'center', flexWrap: 'wrap' }}>
              {!pet.active && (
                <button className="tool-btn" onClick={() => selectPet(pet.id)}>
                  select
                </button>
              )}
              <button className="tool-btn" onClick={() => inspectPet(pet.id)}>
                inspect
              </button>
              <button className="tool-btn" onClick={() => exportPetZip(pet.id)}>
                export .pet.zip
              </button>
              <input
                aria-label={`Rename ${pet.id}`}
                value={renameValues[pet.id] || ''}
                onChange={(ev) => setRenameValues((prev) => ({ ...prev, [pet.id]: ev.target.value }))}
                placeholder="new name"
                style={{ width: 90, padding: '2px 5px', fontSize: 10.5 }}
              />
              <button className="tool-btn" onClick={() => renamePet(pet.id)}>
                rename
              </button>
              {!pet.builtin &&
                (confirmDeleteId === pet.id ? (
                  <button className="tool-btn" onClick={() => deleteCustomPet(pet.id)}>
                    confirm delete
                  </button>
                ) : (
                  <button className="tool-btn" onClick={() => setConfirmDeleteId(pet.id)}>
                    delete
                  </button>
                ))}
            </div>
          </div>
        ))}
      </div>

      {/* .pet.zip Import / Export */}
      <div style={{ display: 'flex', gap: 6, marginBottom: 8 }}>
        <input
          aria-label="Import .pet.zip base64"
          value={importB64}
          onChange={(ev) => setImportB64(ev.target.value)}
          placeholder="paste .pet.zip base64 archive..."
          style={{ flex: 1, padding: '4px 6px', fontSize: 10.5 }}
        />
        <button className="tool-btn" onClick={importPetZip}>
          import .pet.zip
        </button>
      </div>
      {exportNote && <div style={{ fontSize: 10.5, color: 'var(--ink-2)', marginBottom: 6 }}>{exportNote}</div>}

      {thumbUri && (
        <div style={{ marginBottom: 6 }}>
          <img src={thumbUri} alt="companion thumbnail" width={48} height={48} style={{ imageRendering: 'pixelated' }} />
        </div>
      )}
      {inspectDetail && (
        <pre style={{ fontSize: 10, padding: 6, overflowX: 'auto', marginBottom: 6 }}>{inspectDetail}</pre>
      )}
      {doctor && (
        <div style={{ fontSize: 10.5, marginBottom: 6 }}>
          {doctor.checks.map((c) => (
            <div key={c.name}>
              {c.ok ? '✓' : '✗'} <code>{c.name}</code>: {c.detail}
            </div>
          ))}
        </div>
      )}
      {statusNote && <div style={{ fontSize: 11, color: 'var(--accent-light)' }}>{statusNote}</div>}
    </Card>
  );
}
