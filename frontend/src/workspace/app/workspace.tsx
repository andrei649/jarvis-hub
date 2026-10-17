/* State shared by every signed-in screen: the departments the user may work in, the one
   currently selected in the sidebar switcher, and the shell counters (pending approvals).

   The selected department is remembered per user in this browser and validated against the
   server's list on every load, so a department the user lost access to is never used. Pages
   that change departments (admin) or decide approvals call the refresh functions, which keeps
   the sidebar honest without polling for everything. */
import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { listDepartments, pendingApprovalsCount } from '../api/account';
import type { Department } from '../api/types';
import { usePolling } from './hooks';
import { useSession } from './session';
import { readPref, writePref } from './storage';

export interface WorkspaceContextValue {
  departments: Department[];
  departmentsLoaded: boolean;
  departmentsError: unknown;
  currentDepartment: Department | null;
  setCurrentDepartmentId: (id: number) => void;
  refreshDepartments: () => Promise<void>;
  pendingApprovals: number;
  refreshPendingApprovals: () => Promise<void>;
}

const WorkspaceContext = createContext<WorkspaceContextValue | null>(null);
const APPROVALS_POLL_MS = 60_000;

export function WorkspaceProvider({ children }: { children: React.ReactNode }) {
  const { user, session } = useSession();
  const userId = user?.id ?? null;
  const [departments, setDepartments] = useState<Department[]>(session?.departments ?? []);
  const [departmentsLoaded, setLoaded] = useState(false);
  const [departmentsError, setError] = useState<unknown>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [pendingApprovals, setPending] = useState(0);

  const refreshDepartments = useCallback(async () => {
    try {
      const list = await listDepartments();
      setDepartments(list);
      setError(null);
    } catch (err) {
      setError(err);
    } finally {
      setLoaded(true);
    }
  }, []);

  useEffect(() => {
    if (userId === null) return;
    const stored = Number(readPref(`department.${userId}`));
    setSelectedId(Number.isFinite(stored) && stored > 0 ? stored : null);
    void refreshDepartments();
  }, [userId, refreshDepartments]);

  const setCurrentDepartmentId = useCallback((id: number) => {
    setSelectedId(id);
    if (userId !== null) writePref(`department.${userId}`, String(id));
  }, [userId]);

  const refreshPendingApprovals = useCallback(async () => {
    try {
      setPending(await pendingApprovalsCount());
    } catch {
      // The badge is advisory: a failed poll keeps the last known count instead of a fake zero.
    }
  }, []);
  usePolling(refreshPendingApprovals, APPROVALS_POLL_MS, userId !== null);

  // Default to a department the user belongs to (admins can use every department, but their
  // own membership is the sensible starting point), then to the first one listed.
  const memberOf = user?.department_ids;
  const currentDepartment = useMemo(
    () => departments.find((d) => d.id === selectedId)
      ?? departments.find((d) => memberOf?.includes(d.id))
      ?? departments[0] ?? null,
    [departments, selectedId, memberOf],
  );

  const value = useMemo<WorkspaceContextValue>(() => ({
    departments, departmentsLoaded, departmentsError, currentDepartment, setCurrentDepartmentId,
    refreshDepartments, pendingApprovals, refreshPendingApprovals,
  }), [departments, departmentsLoaded, departmentsError, currentDepartment, setCurrentDepartmentId,
    refreshDepartments, pendingApprovals, refreshPendingApprovals]);

  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}

export function useWorkspace(): WorkspaceContextValue {
  const ctx = useContext(WorkspaceContext);
  if (!ctx) throw new Error('useWorkspace outside WorkspaceProvider');
  return ctx;
}
