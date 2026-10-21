/* A readable "browser on system" for the active-sessions list, from the stored User-Agent.
   Order matters: Edge and Opera also say "Chrome", Chrome also says "Safari". Unknown agents
   return null and the caller shows a neutral label instead of a guess. */
export interface AgentSummary { browser: string | null; os: string | null }

const BROWSERS: [RegExp, string][] = [
  [/Edg(e|A|iOS)?\//, 'Edge'], [/OPR\/|Opera/, 'Opera'], [/Firefox\/|FxiOS\//, 'Firefox'],
  [/Chrome\/|CriOS\//, 'Chrome'], [/Safari\//, 'Safari'],
];
const SYSTEMS: [RegExp, string][] = [
  [/Windows NT/, 'Windows'], [/iPhone|iPad|iPod/, 'iOS'], [/Mac OS X|Macintosh/, 'macOS'],
  [/Android/, 'Android'], [/CrOS/, 'ChromeOS'], [/Linux/, 'Linux'],
];

export function summarizeAgent(agent: string): AgentSummary {
  const browser = BROWSERS.find(([pattern]) => pattern.test(agent))?.[1] ?? null;
  const os = SYSTEMS.find(([pattern]) => pattern.test(agent))?.[1] ?? null;
  return { browser, os };
}
