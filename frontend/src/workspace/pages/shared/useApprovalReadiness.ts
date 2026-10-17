/* Can a request of this kind succeed right now? Screens ask before they offer one: the
   eligibility probe counts the people (other than the caller) who could decide it, and for
   email kinds it also tells whether outgoing email is configured, so an email action that
   could never be delivered is not shown at all. Admins can read the SMTP settings directly,
   which covers a server that answers the probe with the count alone. */
import { useCallback, useEffect, useRef, useState } from 'react';
import { getSmtp, smtpConfigured } from '../../api/admin';
import { eligibleDeciders, type ApprovalKind } from '../../api/approvals';
import { useUser } from '../../app/session';

const EMAIL_KINDS: ReadonlySet<ApprovalKind> = new Set(['email.send', 'report.delivery']);

export interface ApprovalReadiness {
  loading: boolean;
  /** People who could decide the request; null until known. */
  count: number | null;
  /** For email kinds: true/false once known, null when the server does not say. */
  smtpReady: boolean | null;
  error: unknown;
  reload: () => Promise<void>;
}

export function useApprovalReadiness(kind: ApprovalKind, departmentId: number | null, enabled = true): ApprovalReadiness {
  const user = useUser();
  const isAdmin = user.role === 'admin';
  const [state, setState] = useState<Omit<ApprovalReadiness, 'reload'>>({ loading: enabled, count: null, smtpReady: null, error: null });
  const seq = useRef(0);

  const reload = useCallback(async () => {
    const mine = ++seq.current;
    setState((prev) => ({ ...prev, loading: true, error: null }));
    try {
      const probe = await eligibleDeciders(kind, departmentId);
      let smtpReady: boolean | null = null;
      if (EMAIL_KINDS.has(kind)) {
        if (typeof probe.smtp_configured === 'boolean') smtpReady = probe.smtp_configured;
        else if (isAdmin) smtpReady = smtpConfigured(await getSmtp());
      }
      if (mine === seq.current) setState({ loading: false, count: Number(probe.count) || 0, smtpReady, error: null });
    } catch (err) {
      if (mine === seq.current) setState({ loading: false, count: null, smtpReady: null, error: err });
    }
  }, [kind, departmentId, isAdmin]);

  useEffect(() => {
    if (!enabled) return undefined;
    void reload();
    return () => { seq.current += 1; };
  }, [enabled, reload]);

  return { ...state, reload };
}
