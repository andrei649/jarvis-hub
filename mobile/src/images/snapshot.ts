import * as Crypto from 'expo-crypto';

export type PickerImage = { type?: string | null; base64?: string | null; width?: number; height?: number;
  mimeType?: string | null; fileSize?: number | null };
export type SelectedSnapshot = { dataUri: string; digest: string; mime: 'image/png' | 'image/jpeg' | 'image/webp';
  byteCount: number; width: number; height: number };
export const MAX_NEW_IMAGES = 4;
export const MAX_NEW_BYTES = 8 * 1024 * 1024;
export const MAX_IMAGE_BYTES = 4 * 1024 * 1024;
const unsupported = () => new Error('Selected image is unsupported or too large');
const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
function prefixBytes(base64: string, count: number): number[] {
  const result: number[] = [];
  for (let i = 0; i < Math.min(base64.length, Math.ceil(count / 3) * 4); i += 4) {
    const a = alphabet.indexOf(base64[i]); const b = alphabet.indexOf(base64[i + 1]);
    const c = alphabet.indexOf(base64[i + 2]); const d = alphabet.indexOf(base64[i + 3]);
    result.push((a << 2) | (b >> 4));
    if (c >= 0) result.push(((b & 15) << 4) | (c >> 2));
    if (d >= 0) result.push(((c & 3) << 6) | d);
  }
  return result.slice(0, count);
}
const eq = (a: number[], b: number[]) => b.every((v, i) => a[i] === v);
function mimeOf(bytes: number[]): SelectedSnapshot['mime'] | null {
  if (eq(bytes, [137, 80, 78, 71, 13, 10, 26, 10])) return 'image/png';
  if (eq(bytes, [255, 216, 255])) return 'image/jpeg';
  if (eq(bytes, [82, 73, 70, 70]) && eq(bytes.slice(8), [87, 69, 66, 80])
    && (eq(bytes.slice(12), [86, 80, 56, 32]) || eq(bytes.slice(12), [86, 80, 56, 76]))) return 'image/webp';
  return null; // GIF and extended WebP can be animated; native submits static formats only.
}

/** The picker-exported base64 is one immutable snapshot. No mutable file re-read occurs. */
export async function snapshotImage(asset: PickerImage): Promise<SelectedSnapshot> {
  const raw = asset.base64;
  if (asset.type !== 'image' || typeof raw !== 'string' || raw.length < 16
    || raw.length > Math.ceil(MAX_IMAGE_BYTES / 3) * 4 || raw.length % 4 !== 0
    || !/^[A-Za-z0-9+/]+={0,2}$/.test(raw)
    || !Number.isSafeInteger(asset.width) || !Number.isSafeInteger(asset.height)
    || (asset.width as number) < 1 || (asset.height as number) < 1
    || (asset.width as number) > 8192 || (asset.height as number) > 8192
    || (asset.width as number) * (asset.height as number) > 16_000_000) throw unsupported();
  const padding = raw.endsWith('==') ? 2 : raw.endsWith('=') ? 1 : 0;
  const bytes = raw.length / 4 * 3 - padding;
  if (bytes < 1 || bytes > MAX_IMAGE_BYTES || (padding && raw.slice(0, -padding).includes('='))) throw unsupported();
  const mime = mimeOf(prefixBytes(raw, 24));
  if (!mime) throw unsupported();
  const dataUri = `data:${mime};base64,${raw}`;
  const hash = await Crypto.digestStringAsync(Crypto.CryptoDigestAlgorithm.SHA256, dataUri);
  if (!/^[0-9a-f]{64}$/.test(hash)) throw unsupported();
  return { dataUri, digest: hash, mime, byteCount: bytes,
    width: asset.width as number, height: asset.height as number };
}
