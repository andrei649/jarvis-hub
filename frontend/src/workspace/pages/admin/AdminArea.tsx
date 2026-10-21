/* The admin console frame: one heading, section tabs (real links, one URL per section), and
   the active section. Only admins reach it (routes.tsx), and the server enforces it per call. */
import React from 'react';
import type { AdminSection } from '../../routes';
import { useI18n, type MessageKey } from '../../i18n';
import { useDocumentTitle } from '../../router';
import { NavTabs, PageHeader } from '../../ui';
import { AuditSection } from './AuditSection';
import { DepartmentsSection } from './DepartmentsSection';
import { EmailSection } from './EmailSection';
import { OrganisationSection } from './OrganisationSection';
import { UsageSection } from './UsageSection';
import { UsersSection } from './UsersSection';

const SECTIONS: { id: AdminSection; label: MessageKey; desc: MessageKey }[] = [
  { id: 'users', label: 'admin.users', desc: 'admin.users.desc' },
  { id: 'departments', label: 'admin.departments', desc: 'admin.departments.desc' },
  { id: 'organisation', label: 'admin.organisation', desc: 'admin.organisation.desc' },
  { id: 'email', label: 'admin.email', desc: 'admin.email.desc' },
  { id: 'audit', label: 'admin.audit', desc: 'admin.audit.desc' },
  { id: 'usage', label: 'admin.usage', desc: 'admin.usage.desc' },
];

const CONTENT: Record<AdminSection, () => React.ReactElement> = {
  users: () => <UsersSection />,
  departments: () => <DepartmentsSection />,
  organisation: () => <OrganisationSection />,
  email: () => <EmailSection />,
  audit: () => <AuditSection />,
  usage: () => <UsageSection />,
};

export function AdminArea({ section }: { section: AdminSection }) {
  const { t } = useI18n();
  const active = SECTIONS.find((s) => s.id === section) ?? SECTIONS[0];
  useDocumentTitle(`${t(active.label)} · ${t('nav.admin')}`);
  return (
    <>
      <PageHeader eyebrow={t('nav.admin')} title={t(active.label)} description={t(active.desc)} />
      <NavTabs
        label={t('admin.sectionsLabel')}
        items={SECTIONS.map((s) => ({ to: `/admin/${s.id}`, label: t(s.label), active: s.id === section }))}
      />
      <div className="ws-section">{CONTENT[section]()}</div>
    </>
  );
}
