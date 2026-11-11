/* H132 — the page-header slot: a page puts its own toolbar beside the page title.

   The shell renders <PageHeaderBar> above the current page inside a <PageHeaderProvider>
   keyed on the mode. A page calls `usePageHeader(node, deps)`; the node shows in the bar
   while that page is mounted, and is cleared when the page unmounts or the mode changes
   (the provider drops whatever the previous page left, so a toolbar never leaks onto the
   next page). Outside a provider (a panel rendered in the Console overlay) the hook does
   nothing, so a panel can use it unconditionally. */
import React, { createContext, useContext, useEffect, useId, useLayoutEffect, useState } from 'react';

type Entry = { owner: string; node: React.ReactNode } | null;
type Setter = (owner: string, node: React.ReactNode | null) => void;

const SetterCtx = createContext<Setter | null>(null);
const ValueCtx = createContext<Entry>(null);

export function PageHeaderProvider({ routeKey, children }: { routeKey: string; children: React.ReactNode }) {
  const [entry, setEntry] = useState<Entry>(null);
  const [set] = useState<Setter>(() => (owner, node) => setEntry((cur) => {
    if (node == null) return cur && cur.owner === owner ? null : cur;
    return { owner, node };
  }));
  // A mode change clears the slot before the next page paints its own toolbar.
  useLayoutEffect(() => { setEntry(null); }, [routeKey]);
  return <SetterCtx.Provider value={set}><ValueCtx.Provider value={entry}>{children}</ValueCtx.Provider></SetterCtx.Provider>;
}

/** Put `node` in the page header while the calling page is mounted; `deps` re-set it. */
export function usePageHeader(node: React.ReactNode, deps: React.DependencyList = []) {
  const set = useContext(SetterCtx);
  const owner = useId();
  useEffect(() => {
    if (!set) return undefined;
    set(owner, node);
    return () => set(owner, null);
  }, [set, owner, ...deps]); // eslint-disable-line react-hooks/exhaustive-deps
}

/** The page title plus whatever toolbar the current page registered; nothing when it has none. */
export function PageHeaderBar({ title }: { title: React.ReactNode }) {
  const entry = useContext(ValueCtx);
  if (!entry || entry.node == null) return null;
  return (
    <div className="page-head" data-anchor="page-head">
      <span className="page-head-title">{title}</span>
      <div className="page-head-actions" role="toolbar" aria-label="page actions">{entry.node}</div>
    </div>
  );
}
