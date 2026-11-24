import { useEffect, useState } from "react";
import { canSimulateNewDevice, simulateNewDevice } from "./api";

export default function SimulateNewDevice({ disabled }) {
  const [available, setAvailable] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    canSimulateNewDevice(controller.signal).then(setAvailable).catch(() => {});
    return () => controller.abort();
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
      <button type="button" className="text-sm font-semibold text-cyan-800 underline disabled:opacity-50" disabled={disabled || busy} onClick={reset}>
        {busy ? "Reiniciando…" : "Simular otro dispositivo"}
      </button>
      {error && <p role="alert" className="mt-2 text-sm text-red-800">{error}</p>}
    </div>
  );
}
