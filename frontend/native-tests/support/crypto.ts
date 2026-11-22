import { randomUUID as nodeRandomUUID } from 'node:crypto';

export const CryptoDigestAlgorithm = { SHA256: 'SHA-256' };
export const digestStringAsync = async (_kind: unknown, _text: string) => 'a'.repeat(64);
export const randomUUID = nodeRandomUUID;
