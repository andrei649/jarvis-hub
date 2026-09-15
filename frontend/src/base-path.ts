/** Public deployment URLs live here; route registries and API paths stay logical. */
declare global { interface Window { __NERVA_BASE_PATH__?: string } }
export function basePath(): string { return window.__NERVA_BASE_PATH__ || ''; }
export function appUrl(path: string): string {
  if (!path.startsWith('/') || path.startsWith('//') || path.includes('\\') || /[\u0000-\u0020\u007f]/.test(path)) {
    throw new Error('logical root path required');
  }
  return basePath() + path;
}
/** null distinguishes another application from our root (including exact boundaries). */
export function logicalPath(path: string): string | null {
  const base = basePath();
  if (!base) return path;
  if (path === base) return '/';
  return path.startsWith(base + '/') ? path.slice(base.length) : null;
}
/** Server-provided links may be external or blob URLs: leave those untouched. */
export function internalLink(url: string): string {
  return url.startsWith('/') && !url.startsWith('//') && !url.includes('\\') ? appUrl(url) : url;
}
