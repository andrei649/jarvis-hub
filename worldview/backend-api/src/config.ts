// Environment-derived config for the 4D API. Kept tiny and dependency-free.
export const config = {
  port: Number(process.env.PORT ?? 4000),
  host: process.env.HOST ?? "0.0.0.0",
  databaseUrl:
    process.env.DATABASE_URL ?? "postgres://worldview:worldview@localhost:5432/worldview",
  redisUrl: process.env.REDIS_URL ?? "redis://localhost:6379",
  corsOrigin: process.env.CORS_ORIGIN ?? "http://localhost:3000",
  kafkaBrokers: (process.env.KAFKA_BROKERS ?? "localhost:9092").split(","),
  // The live-writer (Kafka -> Redis) and history-writer (Kafka -> TimescaleDB) are opt-in so
  // the API can run without a broker.
  enableLiveWriter: process.env.ENABLE_LIVE_WRITER === "1",
  enableHistoryWriter: process.env.ENABLE_HISTORY_WRITER === "1",
  // The recon-writer (Kafka -> TimescaleDB recon_windows) is opt-in too.
  enableReconWriter: process.env.ENABLE_RECON_WRITER === "1",
  // AuthN/Z (ticket H19.4.2): the HS256 verification key for the "OIDC-style" bearer. When EMPTY
  // (the default) auth is DISABLED and all routes are open (back-compat for tests + the integration
  // CI job); when set, the request guard enforces RBAC + AOI scoping fail-CLOSED.
  authSecret: process.env.WORLDVIEW_AUTH_SECRET ?? "",
  // Live WebSocket fleet scaling (ticket H19.5.2). Coalescing bounds each client's outbound delta
  // rate; geohash sharding scopes a client to only the channels covering its viewport.
  //   wsCoalesceMs       — flush interval for per-client delta coalescing (0 disables coalescing →
  //                        immediate send, the pre-H19.5.2 back-compat behavior).
  //   wsCoalesceMaxBatch — flush early once this many distinct entities are buffered.
  //   wsMaxClientQueue   — hard cap on buffered distinct entities per client (drop-oldest backpressure).
  //   wsGeohashPrecision — geohash char count for channel cells (3 ≈ 150km cells). 0 disables sharding.
  wsCoalesceMs: Number(process.env.WS_COALESCE_MS ?? 100),
  wsCoalesceMaxBatch: Number(process.env.WS_COALESCE_MAX_BATCH ?? 500),
  wsMaxClientQueue: Number(process.env.WS_MAX_CLIENT_QUEUE ?? 5000),
  wsGeohashPrecision: Number(process.env.WS_GEOHASH_PRECISION ?? 3),
  // OTLP tracing (ticket H19.5.5) — strictly OPT-IN. Tracing is initialized ONLY when
  // otelExporterOtlpEndpoint is non-empty; otherwise the OpenTelemetry SDK is never started (no
  // collector required, no effect on tests/CI). otelServiceName labels the emitted spans.
  otelExporterOtlpEndpoint: process.env.OTEL_EXPORTER_OTLP_ENDPOINT ?? "",
  otelServiceName: process.env.OTEL_SERVICE_NAME ?? "worldview-api",
};
