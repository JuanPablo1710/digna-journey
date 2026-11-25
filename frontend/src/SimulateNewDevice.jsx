import { useState } from "react";
import { canSimulateNewDevice, simulateNewDevice } from "./api";
import useAbortableEffect from "./useAbortableEffect";

export default function SimulateNewDevice({ disabled }) {
  const [available, setAvailable] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useAbortableEffect((signal) => {
    canSimulateNewDevice(signal).then((value) => {
      if (!signal.aborted) setAvailable(value);
    }).catch(() => {});
  }, []);

  async function reset() {
    setBusy(true);
    setError("");
    try {
      await simulateNewDevice();
    } catch (reason) {
      setError(reason.message);
      setBusy(false);
    }
  }

  if (!available) return null;
  return (
    <div className="mx-auto max-w-5xl px-5 py-3">
      <button type="button" className="text-sm font-semibold text-primary-strong underline disabled:opacity-50" disabled={disabled || busy} onClick={reset}>
        {busy ? "Reiniciando…" : "Simular otro dispositivo"}
      </button>
      {error && <p role="alert" className="mt-2 text-sm text-danger">{error}</p>}
    </div>
  );
}
