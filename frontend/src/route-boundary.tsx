import React, { Suspense } from 'react';

const messageStyle = (overlay = false): React.CSSProperties => overlay ? { position: 'fixed', inset: '10% 5% auto', zIndex: 90, padding: 24, background: 'var(--void-2)', border: '1px solid var(--panel-line)' } : { padding: 24 };

export function RouteFallback({ overlay = false }: { overlay?: boolean }) { return <div role="status" aria-live="polite" style={messageStyle(overlay)}>Loading page…</div>; }

class RouteError extends React.Component<{ children: React.ReactNode; overlay?: boolean }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() {
    if (this.state.failed) return <div role="alert" style={messageStyle(this.props.overlay)}>This page could not load. <button className="tool-btn" onClick={() => window.location.reload()}>Reload page</button></div>;
    return this.props.children;
  }
}
export function RouteBoundary({ children, routeKey, overlay = false }: { children: React.ReactNode; routeKey?: string; overlay?: boolean }) {
  return <RouteError key={routeKey} overlay={overlay}><Suspense fallback={<RouteFallback overlay={overlay} />}>{children}</Suspense></RouteError>;
}
