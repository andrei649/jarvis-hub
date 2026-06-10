// dossier-modal.jsx — v0.3 Agent Dossier: fullscreen modal on double-click
// Shows SOUL.md excerpt, model, tier, plugins, memory context, skills, recent interactions.

const { useState, useEffect, useCallback } = React;

// ─── Agent Glyph (large version) ─────────────────────────────────────────────

function DossierGlyph({ path, size = 48 }) {
  return (
    <svg viewBox="-12 -12 24 24" width={size} height={size} className="dossier-glyph">
      <path
        d={path}
        fill="none"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinejoin="round"
      />
    </svg>
  );
}

// ─── Tier Badge ──────────────────────────────────────────────────────────────

function TierBadge({ tier }) {
  const labels = {
    CNS: 'Command',
    BIZ: 'Business',
    SEC: 'Security',
    FND: 'Foundation',
  };
  return (
    <span className={`dossier-tier-badge tier-${tier.toLowerCase()}`}>
      {tier} · {labels[tier] || tier}
    </span>
  );
}

// ─── Status Indicator ────────────────────────────────────────────────────────

function StatusIndicator({ status }) {
  return (
    <span className={`dossier-status status-${status}`}>
      <span className="dossier-status-dot" />
      {status.toUpperCase()}
    </span>
  );
}

// ─── Left Column: Identity ───────────────────────────────────────────────────

function DossierIdentity({ agent, dossier }) {
  if (!dossier) return null;

  return (
    <div className="dossier-col dossier-identity">
      <div className="dossier-section">
        <div className="dossier-section-head">
          <span className="dossier-section-label">IDENTITY</span>
        </div>

        <div className="dossier-archetype">
          <span className="dossier-archetype-label">Archetype</span>
          <span className="dossier-archetype-val">{dossier.archetype}</span>
        </div>

        <div className="dossier-personality">
          <span className="dossier-personality-label">Personality</span>
          <p className="dossier-personality-text">{dossier.personality}</p>
        </div>
      </div>

      <div className="dossier-section">
        <div className="dossier-section-head">
          <span className="dossier-section-label">CONFIGURATION</span>
        </div>

        <div className="dossier-config-grid">
          <div className="dossier-config-row">
            <span className="dossier-config-key">Model</span>
            <span className="dossier-config-val accent">{dossier.model}</span>
          </div>
          <div className="dossier-config-row">
            <span className="dossier-config-key">Channel</span>
            <span className="dossier-config-val">{dossier.channel}</span>
          </div>
          <div className="dossier-config-row">
            <span className="dossier-config-key">Heartbeat</span>
            <span className="dossier-config-val">{dossier.heartbeat}</span>
          </div>
          <div className="dossier-config-row">
            <span className="dossier-config-key">LLM Policy</span>
            <span className={`dossier-config-val policy-${dossier.policy}`}>{dossier.policy}</span>
          </div>
        </div>
      </div>

      <div className="dossier-section">
        <div className="dossier-section-head">
          <span className="dossier-section-label">PLUGINS</span>
        </div>
        <div className="dossier-plugin-list">
          {dossier.plugins.length === 0 ? (
            <span className="dossier-empty">None assigned</span>
          ) : (
            dossier.plugins.map((p, i) => (
              <span key={i} className="dossier-plugin-pill">{p}</span>
            ))
          )}
        </div>
      </div>

      <div className="dossier-section">
        <div className="dossier-section-head">
          <span className="dossier-section-label">SKILLS</span>
        </div>
        <div className="dossier-skills-count">
          <span className="dossier-big-num">{dossier.skills}</span>
          <span className="dossier-big-label">loaded</span>
        </div>
      </div>
    </div>
  );
}

// ─── Right Column: Memory & Activity ─────────────────────────────────────────

function DossierMemory({ agent, dossier, memoryContext }) {
  return (
    <div className="dossier-col dossier-memory">
      <div className="dossier-section">
        <div className="dossier-section-head">
          <span className="dossier-section-label">MEMORY CONTEXT</span>
        </div>
        {dossier.memory_facts > 0 ? (
          <div className="dossier-memory-stats">
            <div className="dossier-memory-stat">
              <span className="dossier-mem-val">{dossier.memory_facts}</span>
              <span className="dossier-mem-label">facts stored</span>
            </div>
          </div>
        ) : (
          <span className="dossier-empty">No memory context yet</span>
        )}

        {memoryContext && Object.keys(memoryContext).length > 0 && (
          <div className="dossier-memory-keys">
            <span className="dossier-memkeys-label">Recent keys:</span>
            <div className="dossier-memkeys-list">
              {Object.keys(memoryContext).slice(0, 5).map((k, i) => (
                <span key={i} className="dossier-memkey">{k}</span>
              ))}
            </div>
          </div>
        )}
      </div>

      <div className="dossier-section">
        <div className="dossier-section-head">
          <span className="dossier-section-label">SOUL.MD EXCERPT</span>
        </div>
        <div className="dossier-soul-excerpt">
          <pre className="dossier-soul-text">{dossier.soul_excerpt || '// No excerpt available'}</pre>
        </div>
      </div>
    </div>
  );
}

// ─── Main Dossier Modal ──────────────────────────────────────────────────────

function DossierModal({ agent, dossier, memoryContext, onClose, onChat, onViewSoul }) {
  useEffect(() => {
    const handleKey = (e) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, [onClose]);

  const handleBackdropClick = useCallback((e) => {
    if (e.target === e.currentTarget) onClose();
  }, [onClose]);

  if (!agent || !dossier) return null;

  return (
    <div className="dossier-backdrop" onClick={handleBackdropClick}>
      <div className="dossier-modal">
        {/* Header */}
        <div className="dossier-head">
          <div className="dossier-head-left">
            <DossierGlyph path={agent.glyph} size={48} />
            <div className="dossier-head-info">
              <div className="dossier-head-name-row">
                <span className="dossier-head-name">{agent.name}</span>
                <StatusIndicator status={agent.status} />
              </div>
              <div className="dossier-head-sub">
                <span className="dossier-head-role">{agent.role}</span>
                <TierBadge tier={agent.tier} />
              </div>
            </div>
          </div>
          <button className="dossier-close" onClick={onClose}>
            <svg viewBox="0 0 24 24" width="20" height="20">
              <path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z" fill="currentColor" />
            </svg>
          </button>
        </div>

        {/* Body: 2 columns */}
        <div className="dossier-body">
          <DossierIdentity agent={agent} dossier={dossier} />
          <DossierMemory agent={agent} dossier={dossier} memoryContext={memoryContext} />
        </div>

        {/* Footer */}
        <div className="dossier-foot">
          <button className="dossier-btn primary" onClick={() => onChat && onChat(agent.id)}>
            <svg viewBox="0 0 24 24" width="14" height="14">
              <path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2z" fill="currentColor" />
            </svg>
            Chat with {agent.name}
          </button>
          <button className="dossier-btn" onClick={() => onViewSoul && onViewSoul(agent.id)}>
            View full SOUL.md
          </button>
          <button className="dossier-btn ghost" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    </div>
  );
}

// Export to global scope
Object.assign(window, {
  DossierModal,
  DossierGlyph,
  TierBadge,
  StatusIndicator,
  DossierIdentity,
  DossierMemory,
});
