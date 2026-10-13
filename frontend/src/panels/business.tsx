import React, { useEffect, useState } from 'react';
import {
  addBusinessConnection, askBusiness, deleteBusinessConnection, getBusinessCatalog,
  getBusinessWorkspace, importBusinessCsv, runBusinessReport, saveBusinessWorkspace,
  syncBusinessConnection,
  type Answer, type BusinessCatalog, type BusinessState, type Connection, type Report, type Workspace,
} from '../api/business';
import './business.css';

function errorText(error: unknown): string {
  const err = error as { body?: { detail?: unknown; error?: unknown; reason?: unknown }; message?: string; status?: number };
  const raw = err?.body?.detail ?? err?.body?.error ?? err?.body?.reason;
  if (typeof raw === 'string') return raw;
  if (raw && typeof raw === 'object' && !Array.isArray(raw) && typeof (raw as { message?: unknown }).message === 'string') return (raw as { message: string }).message;
  if (Array.isArray(raw)) return raw.map((item) => typeof item?.msg === 'string' ? item.msg : '').filter(Boolean).join('; ') || 'Datele trimise nu au fost acceptate.';
  if (err?.status === 401 || err?.status === 403) return 'Nu ai drepturi pentru această acțiune. Verifică accesul de administrator.';
  if (err?.status) return `Cererea a eșuat (${err.status}). Încearcă din nou.`;
  return err?.message || 'Nu am putut contacta Nerva. Încearcă din nou.';
}

function dateLabel(value?: string | null): string {
  if (!value) return 'Niciodată';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat('ro-RO', { dateStyle: 'medium', timeStyle: 'short' }).format(date);
}

function displayValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—';
  if (Array.isArray(value)) return value.map(displayValue).join(', ');
  if (typeof value === 'object') return Object.entries(value).map(([key, item]) => `${key}: ${displayValue(item)}`).join(' · ');
  return String(value);
}

function replaceConnection(current: Connection[], connection: Connection): Connection[] {
  return [connection, ...current.filter((item) => item.id !== connection.id)];
}

const emptyProfile: Workspace = { name: '', industry: '', currency: 'RON', local_only: true };
const templateCopy: Record<string, { name: string; description: string; departments: string }> = {
  ecommerce: { name: 'Comerț online', description: 'Comenzi online și stocuri', departments: 'Vânzări · Operațiuni · Asistență' },
  automotive: { name: 'Auto', description: 'Vânzări auto și relația cu clienții', departments: 'Vânzări · Service · Operațiuni' },
  services: { name: 'Servicii', description: 'Proiecte pentru clienți și oportunități', departments: 'Vânzări · Livrare · Finanțe' },
};
const workflowCopy: Record<string, { name: string; description: string }> = {
  sales_overview: { name: 'Vânzări', description: 'Comenzi completed/processing, separat pe monedă' },
  stock_watch: { name: 'Stocuri', description: 'Produse cu stoc redus sau necunoscut' },
  pipeline_review: { name: 'Oportunități', description: 'Oportunități pe etapă și monedă' },
};
const recordKind: Record<string, string> = { orders: 'comenzi', products: 'produse', deals: 'oportunități' };
const fieldCopy: Record<string, string> = {
  paid_orders: 'Comenzi incluse', excluded_orders: 'Comenzi excluse', sales_by_currency: 'Vânzări pe monedă',
  unknown_amount: 'Sumă necunoscută', products: 'Produse', low_stock: 'Stoc redus', unknown_stock: 'Stoc necunoscut', deals: 'Oportunități',
  value_by_currency: 'Valoare pe monedă', by_stage: 'Pe etape', stock_quantity: 'Stoc', created_at: 'Data',
  status: 'Stare', amount: 'Valoare', total: 'Total', currency: 'Monedă', source: 'Sursă', stage: 'Etapă', name: 'Nume',
};
const fieldLabel = (key: string) => fieldCopy[key] || key.replace(/_/g, ' ');
const credentialLabel: Record<string, string> = { consumer_key: 'Cheie consumator', consumer_secret: 'Secret consumator', access_token: 'Token de acces' };
const activityLabel: Record<string, string> = {
  profile_updated: 'Profil actualizat', connection_added: 'Sursă adăugată', connection_synced: 'Sursă sincronizată',
  connection_error: 'Eroare de sincronizare', connection_removed: 'Sursă eliminată', report_created: 'Raport creat',
};

export function BusinessPanel() {
  const [catalog, setCatalog] = useState<BusinessCatalog | null>(null);
  const [state, setState] = useState<BusinessState | null>(null);
  const [profile, setProfile] = useState<Workspace>(emptyProfile);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [actionError, setActionError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState('');
  const [provider, setProvider] = useState('');
  const [connectionName, setConnectionName] = useState('');
  const [baseUrl, setBaseUrl] = useState('');
  const [credentials, setCredentials] = useState<Record<string, string>>({});
  const [csvName, setCsvName] = useState('');
  const [csvKind, setCsvKind] = useState('orders');
  const [csvText, setCsvText] = useState('');
  const [activeReport, setActiveReport] = useState<Report | null>(null);
  const [question, setQuestion] = useState('');
  const [answer, setAnswer] = useState<Answer | null>(null);

  async function reload() {
    setLoading(true);
    setLoadError('');
    try {
      const [nextCatalog, nextState] = await Promise.all([getBusinessCatalog(), getBusinessWorkspace()]);
      setCatalog(nextCatalog);
      setState(nextState);
      setProfile(nextState.workspace || emptyProfile);
      setProvider((current) => current || nextCatalog.connectors.find((item) => item.id !== 'csv')?.id || '');
    } catch (error) {
      setLoadError(errorText(error));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void reload(); }, []);

  async function perform(key: string, task: () => Promise<void>) {
    setBusy(key);
    setActionError('');
    setNotice('');
    try { await task(); }
    catch (error) { setActionError(errorText(error)); }
    finally { setBusy(''); }
  }

  const enabled = !!(catalog?.enabled && state?.enabled);
  const selectedConnector = catalog?.connectors.find((item) => item.id === provider);
  const reports = state?.reports || [];
  const selectedReport = activeReport || reports[0] || null;

  return <div className="business">
    <header className="business-hero">
      <div className="business-hero__eyebrow">NERVA / BUSINESS</div>
      <div className="business-hero__body">
        <div>
          <h3>{state?.workspace?.name || 'Spațiul companiei'}</h3>
          <p>Sursele, rapoartele și întrebările companiei într-un singur loc.</p>
        </div>
        <span className={`business-pill ${enabled ? 'business-pill--on' : ''}`}>{enabled ? 'Activ' : 'Inactiv'}</span>
      </div>
      {enabled && <div className="business-hero__foot">Datele sunt comune utilizatorilor autentificați ai acestei instalări · {state?.workspace?.local_only ? 'Răspunsuri AI doar locale' : 'Rutare AI conform setărilor Nerva'}</div>}
    </header>

    {loading && <p className="business-message" role="status">Se încarcă spațiul companiei…</p>}
    {loadError && <div className="business-alert" role="alert">{loadError} <button type="button" onClick={() => void reload()}>Reîncearcă</button></div>}
    {!loading && state && catalog && !enabled && <section className="business-card business-off">
      <div className="business-icon">◌</div>
      <h3>Spațiul Business este dezactivat</h3>
      <p>Administratorul poate activa acest spațiu prin setarea <code>NERVA_BUSINESS_ENABLED=1</code> și repornirea serviciului.</p>
      <p>Nu se fac sincronizări sau importuri cât timp este dezactivat.</p>
    </section>}

    {!loading && enabled && state && catalog && <>
      {actionError && <div className="business-alert" role="alert">{actionError}</div>}
      {notice && <div className="business-success" role="status">{notice}</div>}

      <div className="business-grid">
        <section className="business-card business-profile" aria-labelledby="business-profile-title">
          <div className="business-section-head"><div><span className="business-kicker">01 / IDENTITATE</span><h3 id="business-profile-title">Profilul companiei</h3></div><span className="business-quiet">Setări administrator</span></div>
          <p className="business-intro">Alege un domeniu pentru a organiza spațiul. Modelul este un punct de plecare; nu adaugă date demonstrative.</p>
          <form onSubmit={(event) => { event.preventDefault(); void perform('profile', async () => {
            const result = await saveBusinessWorkspace({ ...profile, name: profile.name.trim(), currency: profile.currency.trim().toUpperCase() });
            if (!result?.workspace) throw new Error('Nerva nu a confirmat profilul salvat.');
            setState((current) => current && ({ ...current, workspace: result.workspace }));
            setProfile(result.workspace);
            setNotice('Profilul a fost salvat.');
          }); }}>
            <label>Numele companiei<input required maxLength={120} value={profile.name} onChange={(e) => setProfile({ ...profile, name: e.target.value })} placeholder="Ex. Atelier SRL" /></label>
            <div className="business-form-row">
              <label>Domeniu<select value={profile.industry} onChange={(e) => setProfile({ ...profile, industry: e.target.value })}>
                <option value="">Alege un domeniu</option>{catalog.templates.map((item) => <option key={item.id} value={item.id}>{templateCopy[item.id]?.name || item.name}</option>)}
              </select></label>
              <label>Moneda principală<input required maxLength={3} pattern="[A-Za-z]{3}" title="Cod ISO din trei litere" value={profile.currency} onChange={(e) => setProfile({ ...profile, currency: e.target.value })} placeholder="RON" /></label>
            </div>
            {catalog.templates.filter((item) => item.id === profile.industry).map((item) => <p className="business-template" key={item.id}>{templateCopy[item.id]?.description || item.description} · {templateCopy[item.id]?.departments || item.departments.join(' · ')}</p>)}
            <label className="business-check"><input type="checkbox" checked={profile.local_only} onChange={(e) => setProfile({ ...profile, local_only: e.target.checked })} />Folosește doar modele AI locale pentru întrebările Business</label>
            <button className="business-button" disabled={!!busy} type="submit">{busy === 'profile' ? 'Se salvează…' : 'Salvează profilul'}</button>
          </form>
        </section>

        <section className="business-card business-sources" aria-labelledby="business-sources-title">
          <div className="business-section-head"><div><span className="business-kicker">02 / DATE</span><h3 id="business-sources-title">Surse de date</h3></div><span className="business-count">{state.connections.length}</span></div>
          <p className="business-intro">Conectează sursele explicit. Salvarea cheilor nu dovedește conectarea: prima sincronizare verifică accesul și aduce datele.</p>
          {state.connections.length === 0 ? <div className="business-empty">Nu există surse de date. Conectează un serviciu sau importă un CSV pentru a începe.</div> : <div className="business-list">{state.connections.map((item) => <div className="business-source" key={item.id}>
            <div className="business-source__top"><strong>{item.name}</strong><span className={`business-status business-status--${item.status}`}>{item.status === 'connected' ? 'Conectat' : item.status === 'partial' ? 'Date parțiale' : item.status === 'stale' ? 'Date învechite' : item.status === 'error' ? 'Eroare' : item.status === 'pending' ? 'Neconfirmat' : item.status}</span></div>
            <div className="business-muted">{catalog.connectors.find((connector) => connector.id === item.provider)?.name || item.provider} · Ultima sincronizare: {dateLabel(item.last_sync_at)}</div>
            {item.record_count !== null && item.record_count !== undefined && <div className="business-muted">Înregistrări: {displayValue(item.record_count)}</div>}
            {item.error && <p className="business-inline-error">{item.error}</p>}
            {item.last_sync_at && <p className="business-muted">Datele reprezintă ultima copie disponibilă; pot fi învechite.</p>}
            <div className="business-actions">{item.provider !== 'csv' && <button type="button" disabled={!!busy} onClick={() => void perform(`sync-${item.id}`, async () => {
              const result = await syncBusinessConnection(item.id);
              if (!result?.connection) throw new Error('Sincronizarea nu a returnat o stare verificabilă.');
              setState((current) => current && ({ ...current, connections: replaceConnection(current.connections, result.connection) }));
              setNotice(result.connection.status === 'connected' ? `Sursa ${item.name} a fost sincronizată.` : `Starea sursei ${item.name}: ${result.connection.status}.`);
            })}>{busy === `sync-${item.id}` ? 'Se sincronizează…' : 'Sincronizează'}</button>}
            <button type="button" disabled={!!busy} onClick={() => void perform(`delete-${item.id}`, async () => {
              const result = await deleteBusinessConnection(item.id);
              if (!result?.ok) throw new Error('Ștergerea nu a fost confirmată.');
              setState((current) => current && ({ ...current, connections: current.connections.filter((connection) => connection.id !== item.id) }));
              setNotice(`Sursa ${item.name} a fost eliminată.`);
            })}>Elimină</button></div>
          </div>)}</div>}
          <div className="business-divider" />
          <h4>Conectează un serviciu</h4>
          <form onSubmit={(event) => { event.preventDefault(); void perform('connection', async () => {
            const result = await addBusinessConnection({ provider, name: connectionName.trim(), base_url: baseUrl.trim(), credentials });
            if (!result?.connection) throw new Error('Nerva nu a confirmat sursa.');
            setState((current) => current && ({ ...current, connections: replaceConnection(current.connections, result.connection) }));
            setConnectionName(''); setBaseUrl(''); setCredentials({});
            setNotice('Sursa a fost salvată. Apasă „Sincronizează” pentru a verifica accesul și a prelua date.');
          }); }}>
            <label>Serviciu<select value={provider} onChange={(e) => { setProvider(e.target.value); setBaseUrl(e.target.value === 'hubspot' ? 'https://api.hubapi.com' : ''); setCredentials({}); }}>
              {catalog.connectors.filter((item) => item.id !== 'csv').map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
            </select></label>
            <label>Numele conexiunii<input required maxLength={120} value={connectionName} onChange={(e) => setConnectionName(e.target.value)} placeholder="Ex. Magazin principal" /></label>
            {selectedConnector?.base_url_required && <label>Adresa HTTPS a serviciului<input required type="url" pattern="https://.*" readOnly={provider === 'hubspot'} value={provider === 'hubspot' ? 'https://api.hubapi.com' : baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://magazin.example" /></label>}
            {selectedConnector?.auth_fields.map((field) => <label key={field.key}>{credentialLabel[field.key] || field.label}<input required type={field.secret ? 'password' : 'text'} autoComplete="off" value={credentials[field.key] || ''} onChange={(e) => setCredentials({ ...credentials, [field.key]: e.target.value })} /></label>)}
            <p className="business-muted">Cheile sunt trimise serverului Nerva și păstrate criptat; nu sunt afișate ulterior.</p>
            <button className="business-button" disabled={!!busy || !selectedConnector} type="submit">{busy === 'connection' ? 'Se salvează…' : 'Salvează conexiunea'}</button>
          </form>
          <div className="business-divider" />
          <h4>Importă un fișier CSV</h4>
          <form onSubmit={(event) => { event.preventDefault(); void perform('import', async () => {
            const result = await importBusinessCsv({ name: csvName.trim(), kind: csvKind, csv_text: csvText });
            if (!result?.connection) throw new Error('Importul nu a fost confirmat.');
            setState((current) => current && ({ ...current, connections: replaceConnection(current.connections, result.connection) }));
            setCsvText(''); setCsvName('');
            setNotice('Import finalizat. Datele din CSV sunt disponibile pentru rapoarte.');
          }); }}>
            <div className="business-form-row"><label>Numele sursei CSV<input required maxLength={120} value={csvName} onChange={(e) => setCsvName(e.target.value)} placeholder="Ex. Comenzi octombrie" /></label>
              <label>Tipul datelor<select value={csvKind} onChange={(e) => setCsvKind(e.target.value)}><option value="orders">Comenzi</option><option value="products">Produse</option><option value="deals">Oportunități</option></select></label></div>
            <label>Fișier CSV<input type="file" accept=".csv,text/csv" onChange={(event) => { const file = event.target.files?.[0]; if (!file) return; if (file.size > 1_000_000) { setCsvText(''); setActionError('Fișierul este prea mare (maximum 1 MB).'); return; } void file.text().then(setCsvText).catch(() => setActionError('Fișierul nu a putut fi citit.')); }} /></label>
            <label>Conținut CSV<textarea required rows={4} value={csvText} onChange={(e) => setCsvText(e.target.value)} placeholder="id,status,total,currency,created_at" /></label>
            <button className="business-button" disabled={!!busy || !csvText.trim()} type="submit">{busy === 'import' ? 'Se importă…' : 'Importă CSV'}</button>
          </form>
        </section>
      </div>

      <section className="business-card business-reports" aria-labelledby="business-reports-title">
        <div className="business-section-head"><div><span className="business-kicker">03 / PERSPECTIVĂ</span><h3 id="business-reports-title">Rapoarte</h3></div><span className="business-count">{reports.length}</span></div>
        <p className="business-intro">Rapoartele folosesc doar copiile importate sau sincronizate. Acoperirea și avertismentele arată limitele fiecărui rezultat.</p>
        <div className="business-workflows">{catalog.workflows.map((item) => <article className="business-workflow" key={item.id}>
          <div><h4>{workflowCopy[item.id]?.name || item.name}</h4><p>{workflowCopy[item.id]?.description || item.description}</p><span>Necesită: {recordKind[item.requires] || item.requires}</span></div>
          <button type="button" disabled={!!busy} onClick={() => void perform(`report-${item.id}`, async () => {
            setActiveReport(null);
            const result = await runBusinessReport(item.id);
            if (!result?.report) throw new Error('Nerva nu a returnat un raport.');
            setState((current) => current && ({ ...current, reports: [result.report, ...current.reports.filter((report) => report.id !== result.report.id)] }));
            setActiveReport(result.report);
            setNotice(`Raportul ${workflowCopy[item.id]?.name || item.name} a fost salvat.`);
          })}>{busy === `report-${item.id}` ? 'Se rulează…' : `Rulează ${workflowCopy[item.id]?.name || item.name}`}</button>
        </article>)}</div>
        {reports.length === 0 && !activeReport ? <div className="business-empty">Niciun raport rulat. Alege un raport pentru a vedea rezultatele disponibile.</div> : <div className="business-report-layout">
          <nav className="business-report-list" aria-label="Rapoarte salvate">{reports.map((item) => <button type="button" className={selectedReport?.id === item.id ? 'is-selected' : ''} key={item.id} onClick={() => setActiveReport(item)}><strong>{item.title}</strong><span>{dateLabel(item.created_at)}</span></button>)}</nav>
          {selectedReport && <article className="business-report" aria-label="Raport selectat">
            <div className="business-report__heading"><div><span className="business-kicker">REZULTAT SALVAT</span><h4>{selectedReport.title}</h4></div><time>{dateLabel(selectedReport.created_at)}</time></div>
            <p className="business-report__summary">{selectedReport.summary || 'Nu există un rezumat pentru datele disponibile.'}</p>
            {Object.keys(selectedReport.metrics || {}).length > 0 && <dl className="business-metrics">{Object.entries(selectedReport.metrics).map(([key, value]) => <div key={key}><dt>{fieldLabel(key)}</dt><dd>{displayValue(value)}</dd></div>)}</dl>}
            {(selectedReport.coverage || []).length > 0 ? <div className="business-report__meta"><strong>Acoperire</strong><ul>{selectedReport.coverage.map((item, index) => <li key={index}><strong>{item.source}</strong> · {item.complete ? 'completă' : 'parțială'} · actualizată {dateLabel(item.synced_at)}{item.description ? ` · ${item.description}` : ''}</li>)}</ul></div> : <p className="business-muted">Nu există surse acoperite de acest raport.</p>}
            {(selectedReport.warnings || []).length > 0 && <div className="business-report__warnings"><strong>De verificat</strong><ul>{selectedReport.warnings.map((item, index) => <li key={index}>{item}</li>)}</ul></div>}
            {(selectedReport.rows || []).length > 0 && <div className="business-table-wrap"><table><thead><tr>{Object.keys(selectedReport.rows[0]).map((key) => <th key={key}>{fieldLabel(key)}</th>)}</tr></thead><tbody>{selectedReport.rows.map((row, index) => <tr key={index}>{Object.keys(selectedReport.rows[0]).map((key) => <td key={key}>{displayValue(row[key])}</td>)}</tr>)}</tbody></table></div>}
          </article>}
        </div>}
      </section>

      <section className="business-card business-ask" aria-labelledby="business-ask-title">
        <div className="business-section-head"><div><span className="business-kicker">04 / ÎNTREABĂ</span><h3 id="business-ask-title">Întreabă Nerva</h3></div><span className="business-quiet">Pe baza datelor sincronizate</span></div>
        <p className="business-intro">Nerva recalculează indicatorii din ultimele date sincronizate și păstrează avertismentele surselor. Dacă lipsesc date, răspunsul trebuie citit cu această limită în minte.</p>
        <form onSubmit={(event) => { event.preventDefault(); setAnswer(null); void perform('ask', async () => {
          const result = await askBusiness(question.trim());
          if (!result?.answer) throw new Error('Nerva nu a returnat un răspuns.');
          setAnswer(result);
        }); }}><label>Întrebare despre date<textarea required maxLength={2000} rows={3} value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="De exemplu: Care este valoarea comenzilor incluse, pe fiecare monedă?" /></label><button className="business-button" disabled={!!busy || !question.trim()} type="submit">{busy === 'ask' ? 'Se analizează…' : 'Întreabă Nerva'}</button></form>
        {answer && <div className="business-answer"><span className="business-kicker">Răspuns Nerva · {answer.model} · {answer.route}</span><p>{answer.answer}</p></div>}
      </section>

      <section className="business-card business-activity" aria-labelledby="business-activity-title">
        <div className="business-section-head"><div><span className="business-kicker">05 / ISTORIC</span><h3 id="business-activity-title">Activitate recentă</h3></div><button type="button" disabled={!!busy || loading} onClick={() => void reload()}>Actualizează</button></div>
        {state.activity.length === 0 ? <p className="business-muted">Nu există activitate înregistrată.</p> : <ol>{state.activity.slice(0, 8).map((item, index) => <li key={item.id || index}><span>{activityLabel[item.action || ''] || item.action || 'Acțiune'}{item.label || item.message ? ` · ${item.label || item.message}` : ''}</span><time>{dateLabel(item.created_at || item.at)}</time></li>)}</ol>}
      </section>
    </>}
  </div>;
}
