// Environment-derived config for the 4D API. Kept tiny and dependency-free.
export const config = {
  port: Number(process.env.PORT ?? 4000),
  host: process.env.HOST ?? "0.0.0.0",
  databaseUrl:
    process.env.DATABASE_URL ?? "postgres://worldview:worldview@localhost:5432/worldview",
  redisUrl: process.env.REDIS_URL ?? "redis://localhost:6379",
  corsOrigin: process.env.CORS_ORIGIN ?? "http://localhost:3000",
  kafkaBrokers: (process.env.KAFKA_BROKERS ?? "localhost:9092").split(","),
  // The live-writer (Kafka -> Redis) is opt-in so the API can run without a broker.
  enableLiveWriter: process.env.ENABLE_LIVE_WRITER === "1",
};
