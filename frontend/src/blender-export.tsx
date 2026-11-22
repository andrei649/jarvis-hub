import React, { useMemo, useRef, useState } from 'react';
import { apiExportBlender } from './api/client';

type Face = { indices: number[]; section: number };
type Section = { name: string; faces: number };
type Mesh = { vertices: [number, number, number][]; faces: Face[]; sections: Section[] };

const MAX_BYTES = 256 * 1024;
const NUMBER = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/;

/** The explicit text sent to the selected chat agent; the owner's draft stays separate. */
export function blenderMeshRequest(draft: string): string {
  return `Create an editable Blender model from this brief:\n${draft.trim()}\n\nReturn one complete Wavefront OBJ mesh in a fenced \`\`\`obj block. Use only v x y z, f vertex indices, and o or g names. Use Blender XYZ coordinates with Z up and XY as the ground plane. Follow the brief's named axes exactly. Faces may use positive or negative vertex indices. For closed solids, give all faces consistent outward winding. Use no materials, textures, or other directives. Limit the mesh to 8,192 vertices, 8,192 faces, 64 objects, 64 vertices per face, and coordinates within ±10,000.`;
}

export function parseBlenderObj(source: string): Mesh {
  if (!source.trim() || new TextEncoder().encode(source).length > MAX_BYTES) throw new Error('size');
  const vertices: Mesh['vertices'] = [];
  const faces: Face[] = [];
  const sections: Section[] = [{ name: 'Mesh', faces: 0 }];
  const names = new Set<string>();
  let section = 0;
  for (const original of source.split(/\r\n|\r|\n/)) {
    const line = original.split('#', 1)[0].trim();
    if (!line) continue;
    const parts = line.split(/\s+/);
    const op = parts[0];
    if (op === 'v') {
      if (parts.length !== 4 || parts.slice(1).some(value => !NUMBER.test(value))) throw new Error('syntax');
      const values = parts.slice(1).map(Number) as [number, number, number];
      if (values.some(value => !Number.isFinite(value) || Math.abs(value) > 10000)) throw new Error('bounds');
      vertices.push(values);
      if (vertices.length > 8192) throw new Error('limits');
    } else if (op === 'f') {
      if (parts.length < 4 || parts.length > 65 || parts.slice(1).some(value => !/^[+-]?[0-9]+$/.test(value) || !Number.isSafeInteger(Number(value)) || Number(value) === 0)) throw new Error('syntax');
      const indices = parts.slice(1).map(value => {
        const n = Number(value);
        return n > 0 ? n - 1 : vertices.length + n;
      });
      if (indices.some(index => !Number.isSafeInteger(index) || index < 0 || index >= vertices.length)) throw new Error('indices');
      if (new Set(indices).size !== indices.length) throw new Error('indices');
      faces.push({ indices, section });
      sections[section].faces++;
      if (section === 0) names.add('Mesh');
      if (faces.length > 8192) throw new Error('limits');
    } else if (op === 'o' || op === 'g') {
      const name = line.slice(1).trim();
      if (!name || /[\u0000-\u001f]/.test(name) || new TextEncoder().encode(name).length > 63 || names.has(name)) throw new Error('name');
      names.add(name);
      sections.push({ name, faces: 0 });
      section = sections.length - 1;
      if (sections.length - (sections[0].faces ? 0 : 1) > 64) throw new Error('limits');
    } else throw new Error('syntax');
  }
  if (!vertices.length || !faces.length || sections.slice(1).some(item => !item.faces)) throw new Error('empty');
  if (new Set(faces.flatMap(face => face.indices)).size !== vertices.length) throw new Error('unused');
  if (!sections[0].faces) sections.shift();
  if (sections.length > 64) throw new Error('limits');
  return { vertices, faces, sections };
}

/** Diagnose paired edge direction and signed volume of each closed edge-connected shell. */
function winding(mesh: Mesh): { inconsistent: boolean; inward: boolean } {
  const edges = new Map<string, { face: number; direction: number }[]>();
  mesh.faces.forEach((face, faceIndex) => {
    for (let i = 0; i < face.indices.length; i++) {
      const a = face.indices[i], b = face.indices[(i + 1) % face.indices.length];
      const key = `${face.section}:${Math.min(a, b)}:${Math.max(a, b)}`;
      const entries = edges.get(key) || [];
      entries.push({ face: faceIndex, direction: a < b ? 1 : -1 });
      edges.set(key, entries);
    }
  });
  const neighbors: number[][] = mesh.faces.map(() => []);
  const invalid = mesh.faces.map(() => false);
  let inconsistent = false;
  for (const entries of edges.values()) {
    if (entries.length === 2) {
      const [a, b] = entries;
      neighbors[a.face].push(b.face); neighbors[b.face].push(a.face);
      if (a.direction === b.direction) {
        inconsistent = true;
        invalid[a.face] = invalid[b.face] = true;
      }
    } else for (const entry of entries) invalid[entry.face] = true;
  }
  const seen = new Set<number>();
  for (let first = 0; first < mesh.faces.length; first++) {
    if (seen.has(first)) continue;
    const stack = [first], shell: number[] = [];
    let closed = true;
    seen.add(first);
    while (stack.length) {
      const face = stack.pop()!;
      shell.push(face);
      if (invalid[face]) closed = false;
      for (const next of neighbors[face]) if (!seen.has(next)) { seen.add(next); stack.push(next); }
    }
    if (!closed) continue;
    const origin = mesh.vertices[mesh.faces[first].indices[0]];
    const low = [Infinity, Infinity, Infinity], high = [-Infinity, -Infinity, -Infinity];
    let volume = 0;
    for (const faceIndex of shell) {
      const indices = mesh.faces[faceIndex].indices;
      for (const index of indices) for (let axis = 0; axis < 3; axis++) {
        low[axis] = Math.min(low[axis], mesh.vertices[index][axis]);
        high[axis] = Math.max(high[axis], mesh.vertices[index][axis]);
      }
      const a = mesh.vertices[indices[0]].map((value, axis) => value - origin[axis]);
      for (let i = 1; i < indices.length - 1; i++) {
        const b = mesh.vertices[indices[i]].map((value, axis) => value - origin[axis]);
        const c = mesh.vertices[indices[i + 1]].map((value, axis) => value - origin[axis]);
        volume += (a[0] * (b[1] * c[2] - b[2] * c[1])
          + a[1] * (b[2] * c[0] - b[0] * c[2])
          + a[2] * (b[0] * c[1] - b[1] * c[0])) / 6;
      }
    }
    const span = Math.max(...high.map((value, axis) => value - low[axis]));
    if (volume < -(span ** 3) * 1e-12) return { inconsistent, inward: true };
  }
  return { inconsistent, inward: false };
}

export function hasInconsistentWinding(mesh: Mesh): boolean { return winding(mesh).inconsistent; }
export function hasInwardClosedShell(mesh: Mesh): boolean { return winding(mesh).inward; }

function MeshPreview({ mesh, ro }: { mesh: Mesh; ro: boolean }) {
  const projected = mesh.vertices.map(([x, y, z]) => [x - y, (x + y) * 0.5 - z]);
  const xs = projected.map(point => point[0]);
  const ys = projected.map(point => point[1]);
  const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
  const scale = Math.min(360 / (maxX - minX || 1), 190 / (maxY - minY || 1));
  const point = (index: number) => `${(210 + (projected[index][0] - (minX + maxX) / 2) * scale).toFixed(1)},${(130 + (projected[index][1] - (minY + maxY) / 2) * scale).toFixed(1)}`;
  const shown = mesh.faces.length > 1200 ? mesh.faces.filter((_, i) => i % Math.ceil(mesh.faces.length / 1200) === 0) : mesh.faces;
  return <figure className="blender-model-preview">
    <svg viewBox="0 0 420 260" role="img" aria-label={ro
      ? `Previzualizare proiectată a geometriei: ${mesh.vertices.length} vârfuri, ${mesh.faces.length} fețe, ${mesh.sections.length} obiecte. Axele X și Y sunt oblice, Z este verticală.`
      : `Projected geometry preview: ${mesh.vertices.length} vertices, ${mesh.faces.length} faces, ${mesh.sections.length} objects. X and Y are diagonal, Z is vertical.`}>
      <rect width="420" height="260" rx="8" fill="var(--panel-bg, #101a25)" />
      {shown.map((face, i) => <polygon key={i} points={face.indices.map(point).join(' ')} fill="var(--accent, #77cbd2)" fillOpacity=".16" stroke="var(--accent-light, #a8e6ea)" strokeWidth=".8" strokeLinejoin="round" />)}
      <g transform="translate(43 213)" strokeWidth="2" fontSize="12" fontFamily="sans-serif">
        <path d="M0 0 L18 10" stroke="#ed8a81"/><text x="22" y="16" fill="#ed8a81">X</text>
        <path d="M0 0 L-18 10" stroke="#81b8ed"/><text x="-28" y="17" fill="#81b8ed">Y</text>
        <path d="M0 0 L0 -24" stroke="#a8d884"/><text x="-4" y="-30" fill="#a8d884">Z</text>
      </g>
    </svg>
    <figcaption>{ro ? 'Vedere oblică, scalată pentru încadrare' : 'Oblique view, scaled to fit'}{shown.length !== mesh.faces.length && (ro ? ` · ${shown.length} fețe afișate` : ` · ${shown.length} faces shown`)}</figcaption>
  </figure>;
}

export function BlenderModel({ source, lang }: { source: string; lang?: string }) {
  const ro = lang === 'ro';
  const parsed = useMemo(() => { try { return { mesh: parseBlenderObj(source) }; } catch (error) { return { error: (error as Error).message }; } }, [source]);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState('');
  const pending = useRef(false);
  const mesh = parsed.mesh;
  if (!mesh) return <p className="blender-model-error" role="status">{ro
    ? 'Geometria OBJ nu poate fi exportată: verifică sintaxa, indicii, numele și limitele (256 KiB, 8.192 vârfuri și fețe, 64 obiecte și vârfuri per față).'
    : 'OBJ geometry cannot be exported: check syntax, indices, names, and limits (256 KiB, 8,192 vertices and faces, 64 objects and vertices per face).'}</p>;
  const orientation = winding(mesh);
  const download = async () => {
    if (pending.current) return;
    pending.current = true; setBusy(true); setFailure('');
    try {
      const blob = await apiExportBlender(source);
      const url = URL.createObjectURL(blob);
      try {
        const anchor = document.createElement('a');
        anchor.href = url; anchor.download = 'Nerva model.blend';
        document.body.appendChild(anchor); anchor.click(); anchor.remove();
      } finally { setTimeout(() => URL.revokeObjectURL(url), 1000); }
    } catch (error) {
      const status = (error as { status?: number }).status;
      setFailure([413, 422].includes(status || 0) ? 'content' : 'retry');
    } finally { pending.current = false; setBusy(false); }
  };
  return <section className="blender-model" aria-label={ro ? 'Revizuiește modelul Blender editabil' : 'Review editable Blender model'}>
    <MeshPreview mesh={mesh} ro={ro}/>
    <p><strong>{mesh.vertices.length.toLocaleString()} {ro ? 'vârfuri' : 'vertices'} · {mesh.faces.length.toLocaleString()} {ro ? 'fețe' : 'faces'} · {mesh.sections.length.toLocaleString()} {ro ? 'obiecte' : 'objects'}</strong></p>
    <p className="blender-model-objects">{mesh.sections.map(item => `${item.name} (${item.faces})`).join(' · ')}</p>
    {orientation.inconsistent && <p role="status" className="blender-model-winding">{ro
      ? 'Unele fețe alăturate au orientări diferite. Poți descărca modelul; în Blender, selectează fețele și folosește Recalculate Outside (Shift+N) pentru a recalcula normalele.'
      : 'Some neighboring faces have inconsistent winding. You can still download the model; in Blender, select the faces and use Recalculate Outside (Shift+N) to recalculate normals.'}</p>}
    {orientation.inward && <p role="status" className="blender-model-winding">{ro
      ? 'Un înveliș închis pare orientat spre interior, pe baza volumului semnat. Poți descărca modelul; în Blender, selectează fețele și folosește Recalculate Outside (Shift+N).'
      : 'A closed shell appears to face inward based on signed volume. You can still download the model; in Blender, select the faces and use Recalculate Outside (Shift+N).'}</p>}
    <button type="button" className="tool-btn" disabled={busy || failure === 'content'} onClick={download}>{busy ? (ro ? 'Se pregătește…' : 'Preparing…') : (ro ? 'Descarcă proiectul Blender' : 'Download Blender project')}</button>
    {failure && <p role="alert">{failure === 'content'
      ? (ro ? 'Serverul a refuzat geometria. Revizuiește codul OBJ din răspuns.' : 'The server rejected this geometry. Review the OBJ in the reply.')
      : (ro ? 'Exportul nu a reușit. Verifică conexiunea și încearcă din nou.' : 'Export failed. Check the connection and try again.')}</p>}
  </section>;
}

export function blenderCodeExport(language: string, source: string, lang?: string): React.ReactNode {
  return /^(obj|wavefront)$/i.test(language.trim()) ? <BlenderModel source={source} lang={lang}/> : null;
}

/** Locate the first labeled OBJ fence for an always-reachable message action. */
export function blenderSourceFromReply(text: string): string | null {
  const match = /(?:^|\n) {0,3}(`{3,}|~{3,})(?:obj|wavefront)[ \t]*\r?\n([\s\S]*?)\r?\n[ \t]*\1[ \t]*(?=\r?\n|$)/i.exec(text);
  return match?.[2] || null;
}
