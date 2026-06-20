// @ts-nocheck
import React, { useEffect, useState } from 'react';
import App from './app';
import { V2 } from './data';
import { Icon, ICONS } from './ui';
import { WorldIntelligenceMode } from './modes_world';

function WorldAwareApp() {
  const [open, setOpen] = useState(() => {
    try { return window.location.hash === '#world' || /[?&]world=1/.test(window.location.search); } catch { return false; }
  });

  useEffect(() => {
    function onKey(e) {
      const tag = (e.target && e.target.tagName ? e.target.tagName : '').toLowerCase();
      if (tag === 'input' || tag === 'textarea') return;
      if (e.key.toLowerCase() === 'w') setOpen(true);
      if (e.key === 'Escape') setOpen(false);
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const t = V2.I18N.en;

  return (
    <>
      <App />
      <button
        className="tool-btn"
        onClick={() => setOpen(true)}
        title="World Intelligence (W)"
        style={{ position: 'fixed', left: 16, bottom: 16, zIndex: 60, borderColor: 'var(--accent-dim)', color: 'var(--accent-light)' }}
      >
        <Icon d={ICONS.globe} size={13}/> WORLD
      </button>
      {open && (
        <div
          style={{ position: 'fixed', inset: 0, zIndex: 70, background: 'rgba(4,7,14,.96)', padding: 'var(--gap)', display: 'flex', flexDirection: 'column', gap: 'var(--gap)' }}
        >
          <div className="panel" style={{ flex: '0 0 auto' }}>
            <span className="bk tl"></span><span className="bk tr"></span><span className="bk bl"></span><span className="bk br"></span>
            <div className="panel-head">
              <Icon d={ICONS.globe} size={14}/><span className="ttl">WORLD INTELLIGENCE</span>
              <span className="st">Signal Layer · WorldView · Argus</span>
              <button className="tool-btn" style={{ marginLeft: 10 }} onClick={() => setOpen(false)}>close · esc</button>
            </div>
          </div>
          <div style={{ flex: 1, minHeight: 0 }}>
            <WorldIntelligenceMode t={t} />
          </div>
        </div>
      )}
    </>
  );
}

export default WorldAwareApp;
