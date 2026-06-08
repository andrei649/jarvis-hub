// Per-client delta coalescing (ticket H19.5.2). A Coalescer buffers incoming deltas keyed by
// entity id, keeping only the LATEST value per entity, and flushes a batch on a timer or when a
// max-batch size is hit. This bounds each client's outbound message rate regardless of how fast
// the upstream firehose publishes, and the bounded queue (drop-oldest) prevents a slow client from
// growing memory without limit (backpressure).
//
// The class is deliberately framework-free and time-injectable so it is exhaustively unit-testable
// without real timers; routes/live.ts wires it to setInterval + socket.send.

export interface CoalescerOptions<T> {
  // Extract the coalescing key (entity id) from a delta. Two deltas with the same key collapse to
  // the latest enqueued one.
  keyOf: (delta: T) => string;
  // Flush interval in ms. A timer-driven flush fires at most this often.
  intervalMs: number;
  // Flush immediately once this many *distinct* entities are buffered (latency cap under load).
  maxBatch: number;
  // Hard cap on distinct entities held in the buffer. Beyond this the OLDEST buffered entity is
  // dropped to make room (drop-oldest backpressure), and the drop counter is incremented.
  maxQueue: number;
  // Called with a batch of coalesced deltas to deliver to the client.
  onFlush: (batch: T[]) => void;
}

export interface CoalescerMetrics {
  // Number of deltas that overwrote an already-buffered entity (collapsed, never sent on their own).
  coalesced: number;
  // Number of deltas dropped because the bounded queue was full.
  dropped: number;
  // Number of batches flushed.
  flushes: number;
  // Total deltas delivered across all flushes.
  delivered: number;
}

export class Coalescer<T> {
  // Insertion-ordered map: Map preserves insertion order, which gives us stable within-flush
  // ordering AND an O(1) oldest-key lookup (first key) for drop-oldest.
  private readonly buffer = new Map<string, T>();
  private readonly metrics: CoalescerMetrics = {
    coalesced: 0,
    dropped: 0,
    flushes: 0,
    delivered: 0,
  };
  private timer: ReturnType<typeof setInterval> | null = null;
  private closed = false;

  constructor(private readonly opts: CoalescerOptions<T>) {}

  /**
   * Buffer a delta. If an entity with the same key is already buffered it is replaced in place
   * (latest-wins) WITHOUT changing its position — so a hot entity doesn't reset to the back of the
   * queue and starve others. When the buffer is full and the key is new, the oldest entity is
   * dropped. Triggers an immediate flush if the distinct-entity count reaches maxBatch.
   */
  push(delta: T): void {
    if (this.closed) return;
    const key = this.opts.keyOf(delta);

    if (this.buffer.has(key)) {
      // Replace value but keep insertion position: Map.set on an existing key keeps its order.
      this.buffer.set(key, delta);
      this.metrics.coalesced += 1;
    } else {
      if (this.buffer.size >= this.opts.maxQueue) {
        // Drop the oldest buffered entity (first inserted) to bound memory.
        const oldest = this.buffer.keys().next().value as string | undefined;
        if (oldest !== undefined) this.buffer.delete(oldest);
        this.metrics.dropped += 1;
      }
      this.buffer.set(key, delta);
    }

    if (this.buffer.size >= this.opts.maxBatch) {
      this.flush();
    }
  }

  /** Drain the buffer into a single batch and hand it to onFlush. No-op when empty. */
  flush(): void {
    if (this.buffer.size === 0) return;
    // Insertion order = stable ordering within the flush.
    const batch = [...this.buffer.values()];
    this.buffer.clear();
    this.metrics.flushes += 1;
    this.metrics.delivered += batch.length;
    this.opts.onFlush(batch);
  }

  /** Start the periodic flush timer. Safe to call once; subsequent calls are ignored. */
  start(): void {
    if (this.timer || this.closed) return;
    this.timer = setInterval(() => this.flush(), this.opts.intervalMs);
    // Don't keep the event loop alive solely for this client's flush timer.
    if (typeof this.timer === "object" && this.timer && "unref" in this.timer) {
      (this.timer as { unref: () => void }).unref();
    }
  }

  /** Stop the timer and drop any buffered deltas. Idempotent. */
  close(): void {
    this.closed = true;
    if (this.timer) {
      clearInterval(this.timer);
      this.timer = null;
    }
    this.buffer.clear();
  }

  /** Current number of distinct entities buffered (for tests / introspection). */
  get size(): number {
    return this.buffer.size;
  }

  getMetrics(): Readonly<CoalescerMetrics> {
    return { ...this.metrics };
  }
}
