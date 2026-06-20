import crypto from 'node:crypto';

export function stableId(parts) {
  const input = parts.map(part => String(part ?? '')).join('|');
  return crypto.createHash('sha256').update(input).digest('hex').slice(0, 24);
}
