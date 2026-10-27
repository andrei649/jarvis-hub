/* The signed-in route table (paths are relative to /workspace).

   Part-B screens own their files under pages/<area>/index.tsx and keep the export names used
   here. Admin routes render the 404 page for non-admins — the server answers 403 to them
   anyway, and a hidden area should not advertise itself. */
import React from 'react';
import { useUser } from './app/session';
import { useI18n } from './i18n';
import { ApprovalsPage } from './pages/approvals';
import { AssistantPage } from './pages/assistant';
import { DocumentsPage } from './pages/documents';
import { ProfilePage } from './pages/profile/ProfilePage';
import { SharedReportsPage } from './pages/shared-reports';
import { NotFoundPage } from './pages/system';
import { Redirect, resolveRoute, type RouteDef } from './router';
import { Button, EmptyState, Spinner } from './ui';

// The admin console and the reports views load on demand, so the first chunk carries only the
// screens every user opens (NWS-12). Both keep their named exports; lazy() wants a default.
const AdminArea = React.lazy(() => import('./pages/admin/AdminArea').then((m) => ({ default: m.AdminArea })));
const ReportsPage = React.lazy(() => import('./pages/reports').then((m) => ({ default: m.ReportsPage })));

export const ADMIN_SECTIONS = ['users', 'departments', 'organisation', 'email', 'audit', 'usage'] as const;
export type AdminSection = typeof ADMIN_SECTIONS[number];

function AdminOnly({ children }: { children: React.ReactNode }) {
  const user = useUser();
  return user.role === 'admin' ? <>{children}</> : <NotFoundPage />;
}

function isAdminSection(value: string): value is AdminSection {
  return (ADMIN_SECTIONS as readonly string[]).includes(value);
}

export const ROUTES: RouteDef[] = [
  { path: '/', render: () => <Redirect to="/assistant" /> },
  { path: '/assistant', render: (params) => <AssistantPage params={params} /> },
  { path: '/assistant/:conversationId', render: (params) => <AssistantPage params={params} /> },
  { path: '/documents', render: (params) => <DocumentsPage params={params} /> },
  { path: '/documents/:documentId', render: (params) => <DocumentsPage params={params} /> },
  { path: '/reports', render: (params) => <Lazy id="reports"><ReportsPage params={params} /></Lazy> },
  { path: '/reports/:reportId', render: (params) => <Lazy id="reports"><ReportsPage params={params} /></Lazy> },
  { path: '/report-runs/:runId', render: (params) => <Lazy id="reports"><ReportsPage params={params} /></Lazy> },
  { path: '/shared-reports', render: (params) => <SharedReportsPage params={params} /> },
  { path: '/shared-reports/:runId', render: (params) => <SharedReportsPage params={params} /> },
  { path: '/approvals', render: (params) => <ApprovalsPage params={params} /> },
  { path: '/approvals/:approvalId', render: (params) => <ApprovalsPage params={params} /> },
  { path: '/profile', render: () => <ProfilePage /> },
  { path: '/admin', render: () => <AdminOnly><Redirect to="/admin/users" /></AdminOnly> },
  {
    path: '/admin/:section',
    render: ({ section }) => (isAdminSection(section)
      ? <AdminOnly><Lazy id="admin"><AdminArea section={section} /></Lazy></AdminOnly>
      : <NotFoundPage />),
  },
];

function RouteFallback() {
  const { t } = useI18n();
  return <Spinner label={t('common.loading')} />;
}

function ChunkFailed() {
  const { t } = useI18n();
  return (
    <EmptyState
      icon="refresh"
      title={t('system.chunk.title')}
      body={t('system.chunk.body')}
      action={<Button variant="primary" icon="refresh" onClick={() => window.location.reload()}>{t('common.retry')}</Button>}
    />
  );
}

/* A rejected import() (dropped connection, or a tab still pointing at hashes an upgrade
   replaced) would otherwise unmount the whole app: keep the shell and offer a reload. */
class ChunkBoundary extends React.Component<{ children: React.ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() { return this.state.failed ? <ChunkFailed /> : this.props.children; }
}

/* The boundary sits at the route, not around the whole table: arriving from another page then
   mounts it fresh, so the previous page is gone while the chunk loads and the shell's focus
   handover finds no stale hidden heading (it falls back to <main> and hands over on arrival). */
function Lazy({ id, children }: { id: string; children: React.ReactNode }) {
  return (
    <ChunkBoundary key={id}>
      <React.Suspense fallback={<RouteFallback />}>{children}</React.Suspense>
    </ChunkBoundary>
  );
}

export function SignedInRoutes({ path }: { path: string }) {
  const match = resolveRoute(ROUTES, path);
  if (!match) return <NotFoundPage />;
  return <>{match.route.render(match.params)}</>;
}
