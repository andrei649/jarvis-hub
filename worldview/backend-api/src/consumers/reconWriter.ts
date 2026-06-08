import { Kafka, type Consumer } from "kafkajs";
import type { Pool } from "pg";
import { upsertWindows, type ReconWindowRow } from "../repositories/recon.js";

// Recon-writer consumer (ticket H19.2.2): reads predicted recon windows off Kafka topic
// `osint.recon` and persists them to TimescaleDB via the idempotent `upsertWindows` repo.
// Buffers rows and flushes in batches (~size or ~interval, whichever first); idempotent
// inserts (ON CONFLICT DO NOTHING) make at-least-once delivery safe. Opt-in via
// ENABLE_RECON_WRITER=1. Mirrors historyWriter's batching + flush-on-stop structure.

const TOPIC = "osint.recon";
const BATCH_SIZE = 5000;
const FLUSH_MS = 500;

const isFiniteNumber = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
const isString = (v: unknown): v is string => typeof v === "string";

/**
 * Validate + map a recon contract message (`worldview.recon.v1`) to a `ReconWindowRow`.
 * Pure and unit-tested: returns null when a required field is missing or wrong-typed so the
 * consumer can skip it. The four numeric time/distance/quality fields must be finite numbers,
 * the two identifiers must be strings, norad_id must be a finite number, and sunlit_at_peak
 * must be a boolean.
 */
export function reconMessageToRow(msg: unknown): ReconWindowRow | null {
  if (typeof msg !== "object" || msg === null) return null;
  const m = msg as Record<string, unknown>;

  if (!isFiniteNumber(m.norad_id)) return null;
  if (!isString(m.aoi_id)) return null;
  if (!isString(m.sensor_type)) return null;
  if (!isFiniteNumber(m.t_ingress)) return null;
  if (!isFiniteNumber(m.t_peak)) return null;
  if (!isFiniteNumber(m.t_egress)) return null;
  if (!isFiniteNumber(m.min_distance_km)) return null;
  if (typeof m.sunlit_at_peak !== "boolean") return null;
  if (!isFiniteNumber(m.quality)) return null;

  return {
    norad_id: m.norad_id,
    aoi_id: m.aoi_id,
    sensor_type: m.sensor_type,
    t_ingress: m.t_ingress,
    t_peak: m.t_peak,
    t_egress: m.t_egress,
    min_distance_km: m.min_distance_km,
    sunlit_at_peak: m.sunlit_at_peak,
    quality: m.quality,
  };
}

export async function startReconWriter(pool: Pool, brokers: string[]): Promise<Consumer> {
  const kafka = new Kafka({ clientId: "worldview-recon-writer", brokers });
  const consumer = kafka.consumer({ groupId: "recon-writer" });
  await consumer.connect();
  await consumer.subscribe({ topics: [TOPIC], fromBeginning: false });

  let buffer: ReconWindowRow[] = [];
  const flush = async () => {
    if (buffer.length === 0) return;
    const batch = buffer;
    buffer = [];
    try {
      await upsertWindows(pool, batch);
    } catch {
      // Drop the batch on a write error rather than wedging the consumer; the upstream
      // schema registry is the real guard and Kafka retains the source for replay.
    }
  };

  const timer = setInterval(() => void flush(), FLUSH_MS);

  await consumer.run({
    eachMessage: async ({ message }) => {
      if (!message.value) return;
      let parsed: unknown;
      try {
        parsed = JSON.parse(message.value.toString());
      } catch {
        // Skip a malformed message instead of throwing — an unguarded parse error would stop
        // offset progress and redeliver the poison message forever, wedging the partition.
        return;
      }
      const row = reconMessageToRow(parsed);
      if (!row) return; // skip messages that fail contract validation
      buffer.push(row);
      if (buffer.length >= BATCH_SIZE) await flush();
    },
  });

  const stop = consumer.stop.bind(consumer);
  consumer.stop = async () => {
    clearInterval(timer);
    await flush();
    await stop();
  };
  return consumer;
}
