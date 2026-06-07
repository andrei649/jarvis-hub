import { useEffect, useState } from "react";
import { fetchTrack } from "./api";
import { emptyCollection, type FeatureCollection } from "./types";
import { useTimelineStore } from "./store/useTimelineStore";

const TRAIL_WINDOW_SECONDS = 3600; // show the trailing hour of the selected entity's path

// Fetches the selected entity's trail over [masterTime - 1h, masterTime]. Refetches as the
// master clock advances (bucketed to ~10s) so the trail grows in step with playback.
export function useEntityTrack(): FeatureCollection {
  const selected = useTimelineStore((s) => s.selectedEntity);
  const masterTime = useTimelineStore((s) => s.masterTime);
  const [track, setTrack] = useState<FeatureCollection>(emptyCollection);

  useEffect(() => {
    if (!selected) {
      setTrack(emptyCollection());
      return;
    }
    let cancelled = false;
    fetchTrack(selected.layer, selected.id, masterTime - TRAIL_WINDOW_SECONDS, masterTime).then(
      (fc) => {
        if (!cancelled) setTrack(fc);
      },
    );
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected?.layer, selected?.id, Math.floor(masterTime / 10)]);

  return track;
}
