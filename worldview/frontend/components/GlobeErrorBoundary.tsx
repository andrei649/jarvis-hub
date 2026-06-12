"use client";

import { Component, type ReactNode } from "react";

/**
 * Error boundary around the Deck.gl canvas (UX review P3#17). Without it, a WebGL
 * failure (no GPU, disabled acceleration, driver issue, shader error) renders a
 * silent black screen. With it, the user gets a diagnosis and the recovery steps.
 */
export class GlobeErrorBoundary extends Component<
  { children: ReactNode },
  { error: Error | null }
> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="flex h-full w-full items-center justify-center bg-void p-6">
        <div className="w-[520px] max-w-full rounded-[10px] border border-red/40 bg-surface-2 px-8 py-7 text-sm">
          <div className="text-[21px] font-semibold tracking-[.01em]">
            This machine can&apos;t render the globe.
          </div>
          <p className="mt-2.5 text-[13px] leading-relaxed text-ink/65">
            WorldView needs WebGL for the map and the 3D globe. This usually means GPU
            acceleration is unavailable or disabled.
          </p>
          <ol className="mt-2 list-decimal space-y-0.5 pl-4 text-[12.5px] text-ink/65">
            <li>Enable hardware acceleration in your browser settings.</li>
            <li>Update your graphics drivers.</li>
            <li>Try a current Chrome, Firefox, or Safari.</li>
          </ol>
          <p className="mt-2.5 font-mono text-[10px] text-ink/40">
            {String(this.state.error.message ?? this.state.error).slice(0, 160)}
          </p>
          <button
            onClick={() => location.reload()}
            className="mt-3.5 rounded-md border border-line px-3 py-1.5 font-mono text-[9.5px] tracking-[.08em] text-ink/65 hover:border-signal-dim hover:text-signal-light focus-visible:outline focus-visible:outline-2 focus-visible:outline-signal"
          >
            RELOAD ⟳
          </button>
        </div>
      </div>
    );
  }
}
