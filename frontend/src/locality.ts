/* %-on-device, and — just as important — WHERE the number came from.

   Three sources, and they are not interchangeable:
   - `measured`     a real locality split from /api/analytics/locality (the brand metric);
   - `strict-local` DERIVED from the strict-local governance flag. 100% is a correct
                    inference from "no cloud lane is permitted", but it is not a measurement
                    of anything that ran, and must not be displayed as one;
   - `seeded`       the demo sample.

   Kept out of app.tsx so the derivation itself is testable: the reachable App path is
   exactly what a hand-built props fixture cannot exercise (in demo, locality loading is
   skipped and the loader clears it, so the demo branch is reachable only through here). */
export type LocalitySource = 'measured' | 'strict-local' | 'seeded' | null;

export function localityFigure({ locality = null, trust = null, demo = false }: any = {}) {
  if (locality && locality.local_pct != null) {
    return { pct: locality.local_pct, source: 'measured' as LocalitySource };
  }
  if (trust && trust.strict_local === true) {
    return { pct: 100, source: 'strict-local' as LocalitySource };
  }
  if (demo) return { pct: 87, source: 'seeded' as LocalitySource };
  return { pct: null, source: null as LocalitySource };
}
