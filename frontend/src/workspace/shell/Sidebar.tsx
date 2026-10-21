/* The sidebar: wordmark, department switcher, primary navigation.

   Rendered inline from 1024 px up and inside a drawer below that; the same component serves
   both so the two can never drift. Administrare appears only for admins (the server enforces
   it anyway); Aprobări carries the live count of requests waiting for this user. */
import React from 'react';
import { useUser } from '../app/session';
import { useWorkspace } from '../app/workspace';
import { useI18n, type MessageKey } from '../i18n';
import { Link } from '../router';
import { CountBadge, Icon, Select, Skeleton, type IconName } from '../ui';
import { Wordmark } from './Wordmark';

interface NavItem { to: string; label: MessageKey; icon: IconName; matches: string[] }

const NAV: NavItem[] = [
  { to: '/assistant', label: 'nav.assistant', icon: 'chat', matches: ['/assistant'] },
  { to: '/documents', label: 'nav.documents', icon: 'file', matches: ['/documents'] },
  { to: '/reports', label: 'nav.reports', icon: 'chart', matches: ['/reports', '/report-runs'] },
  { to: '/shared-reports', label: 'nav.sharedReports', icon: 'share', matches: ['/shared-reports'] },
  { to: '/approvals', label: 'nav.approvals', icon: 'approvals', matches: ['/approvals'] },
];
const ADMIN: NavItem = { to: '/admin', label: 'nav.admin', icon: 'settings', matches: ['/admin'] };

function isActive(item: NavItem, path: string): boolean {
  return item.matches.some((prefix) => path === prefix || path.startsWith(`${prefix}/`));
}

function DepartmentSwitcher() {
  const { t } = useI18n();
  const { departments, departmentsLoaded, currentDepartment, setCurrentDepartmentId } = useWorkspace();
  if (!departmentsLoaded && departments.length === 0) {
    return <div className="ws-dept-switch"><Skeleton height={36} radius={10} /></div>;
  }
  if (departments.length === 0) {
    return <p className="ws-dept-switch ws-dept-switch--empty">{t('shell.noDepartments')}</p>;
  }
  return (
    <div className="ws-dept-switch">
      <Select
        label={t('shell.department')}
        value={String(currentDepartment?.id ?? '')}
        onChange={(event) => setCurrentDepartmentId(Number(event.target.value))}
        options={departments.map((d) => ({ value: String(d.id), label: d.name }))}
      />
    </div>
  );
}

export function Sidebar({ path, onNavigate }: { path: string; onNavigate?: () => void }) {
  const { t, tn } = useI18n();
  const user = useUser();
  const { pendingApprovals } = useWorkspace();
  const items = user.role === 'admin' ? [...NAV, ADMIN] : NAV;
  return (
    <div className="ws-sidebar__inner">
      <Link to="/assistant" className="ws-sidebar__brand" onClick={onNavigate} aria-label={t('brand.home')}>
        <Wordmark />
      </Link>
      <DepartmentSwitcher />
      <nav aria-label={t('shell.navLabel')} className="ws-nav">
        <ul>
          {items.map((item) => {
            const active = isActive(item, path);
            return (
              <li key={item.to}>
                <Link to={item.to} className={['ws-nav__link', active && 'is-active'].filter(Boolean).join(' ')} aria-current={active ? 'page' : undefined} onClick={onNavigate}>
                  <Icon name={item.icon} />
                  <span className="ws-nav__label">{t(item.label)}</span>
                  {item.to === '/approvals' && <CountBadge count={pendingApprovals} label={tn('shell.pendingApprovals', pendingApprovals)} />}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>
    </div>
  );
}
