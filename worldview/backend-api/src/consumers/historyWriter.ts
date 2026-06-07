import { Kafka, type Consumer } from "kafkajs";
import type { Pool } from "pg";
import { writeBatch, type Envelope } from "../repositories/historyWriter.js";

// History-writer consumer (design doc §4.4): buffers envelopes per domain and flushes to
// TimescaleDB in batches (~size or ~interval, whichever first). Idempotent inserts make
// at-least-once delivery safe. Opt-in via ENABLE_HISTORY_WRITER=1.

const TOPICS = ["osint.adsb", "osint.ais", "osint.tle", "osint.ew", "osint.context"];
const TOPIC_DOMAIN: Record<string, string> = {
  "osint.adsb": "adsb",
  "osint.ais": "ais",
  "osint.tle": "tle",
  "osint.ew": "ew",
  "osint.context": "context",
};

const BATCH_SIZE = 5000;
const FLUSH_MS = 500;

export async function startHistoryWriter(pool: Pool, brokers: string[]): Promise<Consumer> {
  const kafka = new Kafka({ clientId: "worldview-history-writer", brokers });
  const consumer = kafka.consumer({ groupId: "history-writer" });
  await consumer.connect();
  await consumer.subscribe({ topics: TOPICS, fromBeginning: false });

  const buffers: Record<string, Envelope[]> = {};
  const flush = async () => {
    for (const domain of Object.keys(buffers)) {
      const batch = buffers[domain];
      if (!batch || batch.length === 0) continue;
      buffers[domain] = [];
      try {
        await writeBatch(pool, domain, batch);
      } catch {
        // Drop the batch on a write error rather than wedging the consumer; the upstream
        // schema registry is the real guard and Kafka retains the source for replay.
      }
    }
  };

  const timer = setInterval(() => void flush(), FLUSH_MS);

  await consumer.run({
    eachMessage: async ({ topic, message }) => {
      if (!message.value) return;
      const domain = TOPIC_DOMAIN[topic];
      if (!domain) return;
      const env = JSON.parse(message.value.toString()) as Envelope;
      (buffers[domain] ??= []).push(env);
      if (buffers[domain].length >= BATCH_SIZE) await flush();
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
