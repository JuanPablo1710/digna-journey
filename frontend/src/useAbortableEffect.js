import { useEffect } from "react";

export default function useAbortableEffect(effect, dependencies) {
  useEffect(() => {
    const controller = new AbortController();
    // Let a synchronous mount and cleanup finish before starting network work.
    queueMicrotask(() => {
      if (!controller.signal.aborted) effect(controller.signal);
    });
    return () => controller.abort();
  }, dependencies);
}
