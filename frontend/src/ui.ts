// @ts-nocheck
/* Barrel of shared UI symbols so the ported mode files can import what the
   prototype pulled off `window` (primitives + cockpit + shell), plus V2. */
export * from './primitives';
export * from './cockpit';
export * from './shell';
export { V2 } from './data';
