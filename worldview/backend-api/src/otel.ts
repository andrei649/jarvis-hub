// OpenTelemetry OTLP tracing (ticket H19.5.5) — strictly OPT-IN. The SDK is only started when
// OTEL_EXPORTER_OTLP_ENDPOINT is set; otherwise this is a NO-OP that touches no network and starts
// no background work, so tests / CI / local runs without a collector are unaffected. Init is also
// exception-safe: a misconfigured exporter must never crash the server entrypoint.
//
// The OTLP/HTTP trace exporter + Node auto-instrumentations (http, fastify, pg, ioredis, kafkajs)
// give distributed traces to the collector defined in deploy/observability/otel-collector-config.yaml.
import { config } from "./config.js";

// Loaded lazily so the heavy @opentelemetry/* graph is never imported when tracing is disabled
// (keeps `npm test` startup fast and avoids pulling the SDK into the hot path).
type Shutdown = () => Promise<void>;
let shutdownFn: Shutdown | null = null;

/**
 * Initialize OTLP tracing if (and only if) OTEL_EXPORTER_OTLP_ENDPOINT is configured. Returns true
 * when the SDK was started, false when tracing is disabled (the no-op default). Never throws.
 */
export async function initTracing(): Promise<boolean> {
  if (!config.otelExporterOtlpEndpoint) return false; // disabled → no-op, no network, no SDK import
  if (shutdownFn) return true; // already initialized (idempotent)

  try {
    const { NodeSDK } = await import("@opentelemetry/sdk-node");
    const { OTLPTraceExporter } = await import("@opentelemetry/exporter-trace-otlp-http");
    const { getNodeAutoInstrumentations } = await import(
      "@opentelemetry/auto-instrumentations-node"
    );
    const { resourceFromAttributes } = await import("@opentelemetry/resources");
    const { ATTR_SERVICE_NAME } = await import("@opentelemetry/semantic-conventions");

    const sdk = new NodeSDK({
      resource: resourceFromAttributes({
        [ATTR_SERVICE_NAME]: config.otelServiceName,
      }),
      traceExporter: new OTLPTraceExporter({ url: config.otelExporterOtlpEndpoint }),
      instrumentations: [getNodeAutoInstrumentations()],
    });
    sdk.start();
    shutdownFn = () => sdk.shutdown();
    return true;
  } catch {
    // A bad exporter URL / missing optional dep must not take down the API. Tracing stays off.
    return false;
  }
}

/** Flush + shut down the tracing SDK if it was started. Safe to call when tracing is disabled. */
export async function shutdownTracing(): Promise<void> {
  if (!shutdownFn) return;
  const fn = shutdownFn;
  shutdownFn = null;
  try {
    await fn();
  } catch {
    // best-effort flush on shutdown
  }
}
