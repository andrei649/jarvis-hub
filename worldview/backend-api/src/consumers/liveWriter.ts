import { Kafka, type Consumer } from "kafkajs";
import type Redis from "ioredis";
import { writeLive } from "../repositories/live.js";

// The live-writer consumer (design doc §4.4): reads the OSINT topics and upserts the latest
// state per entity into Redis (idempotent, last-write-wins), publishing a delta per message
// for the WebSocket layer. Runs alongside the API when ENABLE_LIVE_WRITER=1.

const LIVE_TOPICS = ["osint.adsb", "osint.ais", "osint.tle", "osint.ew"];

export async function startLiveWriter(redis: Redis, brokers: string[]): Promise<Consumer> {
  const kafka = new Kafka({ clientId: "worldview-live-writer", brokers });
  const consumer = kafka.consumer({ groupId: "live-writer" });
  await consumer.connect();
  await consumer.subscribe({ topics: LIVE_TOPICS, fromBeginning: false });
  await consumer.run({
    eachMessage: async ({ message }) => {
      if (!message.value) return;
      try {
        await writeLive(redis, JSON.parse(message.value.toString()));
      } catch {
        // Malformed message: skip (the worker-side schema registry is the real guard).
      }
    },
  });
  return consumer;
}
