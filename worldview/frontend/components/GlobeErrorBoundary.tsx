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
      <div className="flex h-full w-full items-center justify-center bg-cockpit p-6">
        <div className="max-w-md rounded-xl border border-red-500/40 bg-red-500/10 p-5 text-sm text-white/90">
          <div className="mb-1.5 font-semibold">The globe failed to render</div>
          <p className="text-white/75">
            WorldView needs WebGL for the 3D globe. This usually means GPU acceleration is
            unavailable or disabled.
          </p>
          <ol className="mt-2 list-decimal space-y-0.5 pl-4 text-white/65">
            <li>Enable hardware acceleration in your browser settings.</li>
            <li>Update your graphics drivers.</li>
            <li>Try a current Chrome, Firefox, or Safari.</li>
          </ol>
          <p className="mt-2 font-mono text-[11px] text-white/40">
            {String(this.state.error.message ?? this.state.error).slice(0, 160)}
          </p>
          <button
            onClick={() => location.reload()}
            className="mt-3 rounded bg-signal/25 px-3 py-1 font-medium text-signal hover:bg-signal/40"
          >
            Reload
          </button>
        </div>
      </div>
    );
  }
}
