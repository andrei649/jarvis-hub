/* H509 — the owner signs in to a networked Nerva from a browser.

   Shown only on a networked origin (a LAN name or address, a tunnel), never on loopback,
   where a fresh box already trusts a direct browser. The screen appears when the hub
   says this browser holds no owner session and the hub has an owner credential to sign
   in with, or when a request answers 401. The owner secret goes to the hub once and is
   never stored by the page; the hub answers with an HttpOnly cookie the page cannot read.
   A guest with a user token can still use that token instead (kept in this browser, as
   before). While signed in, a small corner control offers sign-out and sign-out
   everywhere. */
import React, { useEffect, useState } from 'react';
import {
  isNetworkedOrigin, loadOwnerSession, onOwnerSession, ownerSession, signIn, signInWanted,
  signOut, signOutEverywhere, type OwnerSession,
} from './api/owner-session';
import { getToken, setToken } from './api/client';

function needsSignIn(s: OwnerSession | null, wanted: boolean): boolean {
  if (!s || s.signed_in) return false;
  if (getToken()) return false;               // a guest token is in use; the hub judges it
  return wanted || s.sign_in_available === true;
}

export function OwnerSignIn() {
  const networked = isNetworkedOrigin();
  const [session, setSession] = useState<OwnerSession | null>(ownerSession());
  const [wanted, setWanted] = useState<boolean>(signInWanted());
  const [secret, setSecret] = useState('');
  const [guest, setGuest] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [menu, setMenu] = useState(false);

  useEffect(() => {
    if (!networked) return undefined;
    const off = onOwnerSession((s, w) => { setSession(s); setWanted(w); });
    void loadOwnerSession();
    return off;
  }, [networked]);

  if (!networked) return null;

  if (session?.signed_in) {
    return (
      <div data-testid="owner-session-chip" style={{ position: 'fixed', left: 12, bottom: 12, zIndex: 900,
        fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: '.08em' }}>
        {menu ? (
          <div style={{ display: 'flex', gap: 6 }}>
            <button className="tool-btn" type="button" onClick={() => { void signOut(); setMenu(false); }}>SIGN OUT</button>
            <button className="tool-btn" type="button"
              onClick={() => { void signOutEverywhere(); setMenu(false); }}>SIGN OUT EVERYWHERE</button>
            <button className="tool-btn" type="button" aria-label="close" onClick={() => setMenu(false)}>×</button>
          </div>
        ) : (
          <button className="tool-btn" type="button" onClick={() => setMenu(true)}>OWNER · SIGNED IN</button>
        )}
      </div>
    );
  }

  if (!needsSignIn(session, wanted)) return null;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!secret.trim() || busy) return;
    setBusy(true); setError('');
    if (guest) {
      setToken(secret.trim());
      setSecret('');
      window.location.reload();
      return;
    }
    const result = await signIn(secret.trim());
    setBusy(false);
    setSecret('');
    if (!('message' in result)) { window.location.reload(); return; }
    setError(result.message);
  };

  return (
    <div role="dialog" aria-modal="true" aria-labelledby="owner-sign-in-title" data-testid="owner-sign-in"
      style={{ position: 'fixed', inset: 0, zIndex: 1000, display: 'grid', placeItems: 'center',
        background: 'rgba(3,8,14,.86)', backdropFilter: 'blur(6px)', padding: 16 }}>
      <form onSubmit={submit} style={{ width: 'min(380px, 100%)', display: 'grid', gap: 12, padding: 22,
        background: 'var(--surface, #0b1622)', border: '1px solid var(--panel-line, rgba(120,190,240,.2))',
        borderRadius: 'var(--radius, 6px)', color: 'var(--ink, #d8e6f2)' }}>
        <div id="owner-sign-in-title" style={{ fontFamily: 'var(--font-mono)', letterSpacing: '.14em', fontSize: 12,
          color: 'var(--accent-light, #8fe0ff)' }}>
          {guest ? 'USE A GUEST TOKEN' : 'SIGN IN TO NERVA'}
        </div>
        <div style={{ fontSize: 12.5, lineHeight: 1.45, color: 'var(--ink-2, #9fb3c4)' }}>
          {guest
            ? 'Paste the user token the owner gave you. It is kept in this browser only.'
            : 'This hub is reached over the network. Enter the owner secret (the admin token) to open a session in this browser.'}
        </div>
        <input type="password" autoFocus autoComplete="current-password" value={secret}
          aria-label={guest ? 'Guest token' : 'Owner secret'}
          placeholder={guest ? 'guest token' : 'owner secret'}
          onChange={(e) => setSecret(e.target.value)}
          style={{ padding: '9px 10px', background: 'var(--void-2, #050b12)', color: 'inherit',
            border: '1px solid var(--panel-line, rgba(120,190,240,.2))', borderRadius: 4, fontFamily: 'var(--font-mono)' }} />
        {error ? <div role="alert" style={{ fontSize: 12, color: 'var(--red, #ef4444)' }}>{error}</div> : null}
        <button className="tool-btn" type="submit" disabled={busy || !secret.trim()}
          style={{ justifyContent: 'center' }}>{busy ? 'SIGNING IN…' : guest ? 'USE TOKEN' : 'SIGN IN'}</button>
        <button type="button" onClick={() => { setGuest(!guest); setError(''); setSecret(''); }}
          style={{ background: 'none', border: 0, color: 'var(--ink-2, #9fb3c4)', fontSize: 11.5, cursor: 'pointer',
            textDecoration: 'underline' }}>
          {guest ? 'Sign in as the owner instead' : 'I have a guest token'}
        </button>
      </form>
    </div>
  );
}

export default OwnerSignIn;
