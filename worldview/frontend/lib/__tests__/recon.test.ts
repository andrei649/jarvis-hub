import { test, expect, vi, beforeEach, afterEach } from "vitest";
import { formatEta, fetchReconWindows, fetchReconAlerts } from "../recon";

function okFetch(body: unknown) {
  return vi.fn(async () => ({
    ok: true,
    json: async () => body,
  }));
}

beforeEach(() => vi.stubGlobal("fetch", okFetch({ windows: [], alerts: [] })));
afterEach(() => vi.unstubAllGlobals());

test("formatEta returns 'now' when ingress is at or before now", () => {
  expect(formatEta(1000, 1000)).toBe("now");
  expect(formatEta(900, 1000)).toBe("now");
});

test("formatEta renders sub-minute leads in seconds", () => {
  expect(formatEta(1045, 1000)).toBe("in 45s");
  expect(formatEta(1059, 1000)).toBe("in 59s");
});

test("formatEta renders sub-hour leads in whole minutes", () => {
  expect(formatEta(1000 + 12 * 60, 1000)).toBe("in 12m");
  expect(formatEta(1000 + 59 * 60, 1000)).toBe("in 59m");
});

test("formatEta renders multi-hour leads as 'in Xh Ym' (and drops 0 minutes)", () => {
  expect(formatEta(1000 + 2 * 3600 + 5 * 60, 1000)).toBe("in 2h 5m");
  expect(formatEta(1000 + 2 * 3600, 1000)).toBe("in 2h");
});

test("fetchReconWindows builds /recon/windows with from/to/aoi (floored)", async () => {
  await fetchReconWindows({ aoi: "hormuz", from: 1749200400.7, to: 1749286800.2 });
  const url = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0]![0] as string;
  expect(url).toContain("/recon/windows");
  expect(url).toContain("from=1749200400"); // floored, no fractional seconds
  expect(url).toContain("to=1749286800");
  expect(url).toContain("aoi=hormuz");
});

test("fetchReconWindows omits aoi when not provided and returns parsed windows", async () => {
  const rows = [
    {
      norad_id: 40115,
      aoi_id: "hormuz",
      sensor_type: "sar",
      t_ingress: 1749200000,
      t_peak: 1749200300,
      t_egress: 1749200600,
      min_distance_km: 120.5,
      sunlit_at_peak: true,
      quality: 0.8,
    },
  ];
  vi.stubGlobal("fetch", okFetch({ windows: rows }));
  const out = await fetchReconWindows({ from: 1000, to: 2000 });
  const url = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0]![0] as string;
  expect(url).not.toContain("aoi=");
  expect(out).toEqual(rows);
});

test("fetchReconWindows returns [] on a non-ok response", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: false })));
  const out = await fetchReconWindows({ from: 1, to: 2 });
  expect(out).toEqual([]);
});

test("fetchReconWindows returns [] when fetch throws", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => {
      throw new Error("network down");
    }),
  );
  const out = await fetchReconWindows({ from: 1, to: 2 });
  expect(out).toEqual([]);
});

test("fetchReconAlerts builds /recon/alerts?lead= and returns parsed alerts", async () => {
  const rows = [
    {
      norad_id: 25544,
      aoi_id: "taiwan",
      sensor_type: "eo",
      t_ingress: 1749200000,
      t_peak: 1749200300,
      t_egress: 1749200600,
      min_distance_km: 80,
      sunlit_at_peak: false,
      quality: 0.95,
    },
  ];
  vi.stubGlobal("fetch", okFetch({ alerts: rows }));
  const out = await fetchReconAlerts(900);
  const url = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0]![0] as string;
  expect(url).toContain("/recon/alerts");
  expect(url).toContain("lead=900");
  expect(out).toEqual(rows);
});

test("fetchReconAlerts returns [] on a non-ok response", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: false })));
  const out = await fetchReconAlerts(900);
  expect(out).toEqual([]);
});
