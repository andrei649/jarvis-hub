'use strict';
/* dossier-modal.js — v0.3 Agent Dossier: fullscreen modal on double-click */

// useState, useEffect, useCallback, h sunt deja definite global în components.js

function DossierGlyph({ path, size = 48 }) {
  return h('svg', { viewBox: '-12 -12 24 24', width: size, height: size, className: 'dossier-glyph' },
    h('path', {
      d: path,
      fill: 'none',
      stroke: 'currentColor',
      strokeWidth: '1.4',
      strokeLinejoin: 'round'
    })
  );
}

function TierBadge({ tier }) {
  const labels = { CNS: 'Command', BIZ: 'Business', SEC: 'Security', FND: 'Foundation' };
  return h('span', { className: 'dossier-tier-badge tier-' + tier.toLowerCase() },
    tier + ' · ' + (labels[tier] || tier)
  );
}

function StatusIndicator({ status }) {
  return h('span', { className: 'dossier-status status-' + status },
    h('span', { className: 'dossier-status-dot' }),
    status.toUpperCase()
  );
}

function DossierIdentity({ agent, dossier }) {
  if (!dossier) return null;

  return h('div', { className: 'dossier-col dossier-identity' },
    h('div', { className: 'dossier-section' },
      h('div', { className: 'dossier-section-head' },
        h('span', { className: 'dossier-section-label' }, 'IDENTITY')
      ),
      h('div', { className: 'dossier-archetype' },
        h('span', { className: 'dossier-archetype-label' }, 'Archetype'),
        h('span', { className: 'dossier-archetype-val' }, dossier.archetype)
      ),
      h('div', { className: 'dossier-personality' },
        h('span', { className: 'dossier-personality-label' }, 'Personality'),
        h('p', { className: 'dossier-personality-text' }, dossier.personality)
      )
    ),
    h('div', { className: 'dossier-section' },
      h('div', { className: 'dossier-section-head' },
        h('span', { className: 'dossier-section-label' }, 'CONFIGURATION')
      ),
      h('div', { className: 'dossier-config-grid' },
        h('div', { className: 'dossier-config-row' },
          h('span', { className: 'dossier-config-key' }, 'Model'),
          h('span', { className: 'dossier-config-val accent' }, dossier.model)
        ),
        h('div', { className: 'dossier-config-row' },
          h('span', { className: 'dossier-config-key' }, 'Channel'),
          h('span', { className: 'dossier-config-val' }, dossier.channel)
        ),
        h('div', { className: 'dossier-config-row' },
          h('span', { className: 'dossier-config-key' }, 'Heartbeat'),
          h('span', { className: 'dossier-config-val' }, dossier.heartbeat)
        ),
        h('div', { className: 'dossier-config-row' },
          h('span', { className: 'dossier-config-key' }, 'LLM Policy'),
          h('span', { className: 'dossier-config-val policy-' + dossier.policy }, dossier.policy)
        )
      )
    ),
    h('div', { className: 'dossier-section' },
      h('div', { className: 'dossier-section-head' },
        h('span', { className: 'dossier-section-label' }, 'PLUGINS')
      ),
      h('div', { className: 'dossier-plugin-list' },
        dossier.plugins.length === 0
          ? h('span', { className: 'dossier-empty' }, 'None assigned')
          : dossier.plugins.map((p, i) => h('span', { key: i, className: 'dossier-plugin-pill' }, p))
      )
    ),
    h('div', { className: 'dossier-section' },
      h('div', { className: 'dossier-section-head' },
        h('span', { className: 'dossier-section-label' }, 'SKILLS')
      ),
      h('div', { className: 'dossier-skills-count' },
        h('span', { className: 'dossier-big-num' }, dossier.skills),
        h('span', { className: 'dossier-big-label' }, 'loaded')
      )
    )
  );
}

function DossierMemory({ agent, dossier, memoryContext }) {
  return h('div', { className: 'dossier-col dossier-memory' },
    h('div', { className: 'dossier-section' },
      h('div', { className: 'dossier-section-head' },
        h('span', { className: 'dossier-section-label' }, 'MEMORY CONTEXT')
      ),
      dossier.memory_facts > 0
        ? h('div', { className: 'dossier-memory-stats' },
            h('div', { className: 'dossier-memory-stat' },
              h('span', { className: 'dossier-mem-val' }, dossier.memory_facts),
              h('span', { className: 'dossier-mem-label' }, 'facts stored')
            )
          )
        : h('span', { className: 'dossier-empty' }, 'No memory context yet'),
      memoryContext && Object.keys(memoryContext).length > 0 && h('div', { className: 'dossier-memory-keys' },
        h('span', { className: 'dossier-memkeys-label' }, 'Recent keys:'),
        h('div', { className: 'dossier-memkeys-list' },
          Object.keys(memoryContext).slice(0, 5).map((k, i) =>
            h('span', { key: i, className: 'dossier-memkey' }, k)
          )
        )
      )
    ),
    h('div', { className: 'dossier-section' },
      h('div', { className: 'dossier-section-head' },
        h('span', { className: 'dossier-section-label' }, 'SOUL.MD EXCERPT')
      ),
      h('div', { className: 'dossier-soul-excerpt' },
        h('pre', { className: 'dossier-soul-text' }, dossier.soul_excerpt || '// No excerpt available')
      )
    )
  );
}

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

  return h('div', { className: 'dossier-backdrop', onClick: handleBackdropClick },
    h('div', { className: 'dossier-modal' },
      h('div', { className: 'dossier-head' },
        h('div', { className: 'dossier-head-left' },
          h(DossierGlyph, { path: agent.glyph, size: 48 }),
          h('div', { className: 'dossier-head-info' },
            h('div', { className: 'dossier-head-name-row' },
              h('span', { className: 'dossier-head-name' }, agent.name),
              h(StatusIndicator, { status: agent.status })
            ),
            h('div', { className: 'dossier-head-sub' },
              h('span', { className: 'dossier-head-role' }, agent.role),
              h(TierBadge, { tier: agent.tier })
            )
          )
        ),
        h('button', { className: 'dossier-close', onClick: onClose },
          h('svg', { viewBox: '0 0 24 24', width: 20, height: 20 },
            h('path', {
              d: 'M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z',
              fill: 'currentColor'
            })
          )
        )
      ),
      h('div', { className: 'dossier-body' },
        h(DossierIdentity, { agent, dossier }),
        h(DossierMemory, { agent, dossier, memoryContext })
      ),
      h('div', { className: 'dossier-foot' },
        h('button', { className: 'dossier-btn primary', onClick: () => onChat && onChat(agent.id) },
          h('svg', { viewBox: '0 0 24 24', width: 14, height: 14 },
            h('path', {
              d: 'M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2z',
              fill: 'currentColor'
            })
          ),
          'Chat with ' + agent.name
        ),
        h('button', { className: 'dossier-btn', onClick: () => onViewSoul && onViewSoul(agent.id) },
          'View full SOUL.md'
        ),
        h('button', { className: 'dossier-btn ghost', onClick: onClose }, 'Close')
      )
    )
  );
}

Object.assign(window, { DossierModal, DossierGlyph, TierBadge, StatusIndicator, DossierIdentity, DossierMemory });
