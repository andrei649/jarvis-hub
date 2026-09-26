/* H165 — in-app documentation.

   The owner's user guide, flag table and privacy notes, read-only from the hub's
   allowlist (GET /api/help/docs). Rendered by the shared React-only Markdown
   renderer, so a document can never inject markup into the HUD. ?doc=<slug> picks
   the document, which makes every doc a standalone deep link
   (/v2/console/docs?doc=flags). */
import React, { useEffect, useState } from 'react';
import { internalLink } from '../base-path';
import { Markdown } from '../markdown';
import { Card, State, arr, asLive, mono, useApi } from '../panel-kit';

const DEFAULT_DOC = 'user-guide';

export function docHref(slug: string, anchor = ''): string {
  return internalLink(`/v2/console/docs?doc=${encodeURIComponent(slug)}${anchor ? `#${encodeURIComponent(anchor)}` : ''}`);
}

/** name → section anchor for one document, from GET /api/help/docs (e.g. a setting key → its FLAGS.md section). */
export function sectionIndex(list: any, slug: string): Record<string, string> {
  const doc = (list && Array.isArray(list.docs) ? list.docs : []).find((d: any) => d.slug === slug);
  const index: Record<string, string> = {};
  for (const section of (doc && Array.isArray(doc.sections) ? doc.sections : [])) {
    for (const name of section.names || []) if (!(name in index)) index[name] = section.anchor;
  }
  return index;
}

function initialDoc(): string {
  try {
    return new URLSearchParams(window.location.search).get('doc') || DEFAULT_DOC;
  } catch {
    return DEFAULT_DOC;
  }
}

export function DocsPanel() {
  const list = useApi('/api/help/docs');
  const docs = arr(list.d, 'docs');
  const [slug, setSlug] = useState(initialDoc);
  const doc = useApi(`/api/help/docs/${encodeURIComponent(slug)}`);
  const current = doc.d && doc.d.slug === slug ? doc.d : null;
  // A deep link may name a section (#anchor): bring it into view once the document is in.
  useEffect(() => {
    if (!current) return;
    let anchor = '';
    try { anchor = decodeURIComponent(window.location.hash.slice(1)); } catch { anchor = ''; }
    const target = anchor ? document.getElementById(anchor) : null;
    if (target && typeof target.scrollIntoView === 'function') target.scrollIntoView({ block: 'start' });
  }, [current]);
  return (
    <Card title="DOCUMENTATION" live={asLive(list.d)} sub={current ? current.title : null}
      onReload={() => { list.reload(); doc.reload(); }}>
      <div role="tablist" aria-label="documents" style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 8 }}>
        {docs.map((d: any) => (
          <button key={d.slug} role="tab" className="tool-btn" aria-selected={d.slug === slug}
            disabled={!d.available} title={d.available ? d.title : 'not shipped with this install'}
            onClick={() => setSlug(d.slug)}>
            {d.title}
          </button>
        ))}
      </div>
      <State e={list.e || doc.e} loading={doc.loading} n={current ? 1 : 0} />
      {current && (
        <>
          <div style={{ display: 'flex', gap: 10, alignItems: 'center', marginBottom: 6 }}>
            <a href={docHref(slug)} target="_blank" rel="noopener noreferrer" style={mono}>open in a new tab ↗</a>
            {current.truncated && <span style={{ ...mono, color: 'var(--amber)' }}>shown in part — the file is longer</span>}
          </div>
          <Markdown text={current.markdown} className="md docs-md" />
        </>
      )}
    </Card>
  );
}
