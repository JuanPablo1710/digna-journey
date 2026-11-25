import { useState } from "react";
import { useSearchParams } from "react-router-dom";

import { getMailbox } from "../api";
import useAbortableEffect from "../useAbortableEffect";


export default function Mailbox() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [email, setEmail] = useState(searchParams.get("email") ?? "");
  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function loadMailbox(targetEmail = email, signal) {
    if (!targetEmail) return;
    setLoading(true);
    setError("");
    try {
      const result = await getMailbox(targetEmail, signal);
      if (signal?.aborted) return;
      setMessages(result.messages);
      if (targetEmail !== searchParams.get("email")) setSearchParams({ email: targetEmail });
    } catch (reason) {
      if (!signal?.aborted) {
        setError(reason.message);
        setMessages([]);
      }
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }

  useAbortableEffect((signal) => {
    const initialEmail = searchParams.get("email");
    if (initialEmail) loadMailbox(initialEmail, signal);
  }, []);

  return (
    <main className="min-h-screen bg-slate-100 px-5 py-10">
      <div className="mx-auto max-w-3xl">
        <p className="text-sm font-semibold uppercase tracking-widest text-cyan-700">Buzón de demostración</p>
        <h1 className="mt-1 text-3xl font-bold">Correos simulados</h1>
        <p className="mt-2 text-slate-600">Solo contiene datos ficticios y está disponible cuando el modo demo está activo.</p>

        <form className="mt-8 flex flex-col gap-3 rounded-2xl bg-white p-5 shadow-sm sm:flex-row" onSubmit={(event) => { event.preventDefault(); loadMailbox(); }}>
          <label className="field flex-1">Correo electrónico<input required type="email" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="luis.demo@example.com" /></label>
          <button className="button-primary self-end" disabled={loading}>{loading ? "Consultando..." : "Consultar buzón"}</button>
        </form>

        {error && <div className="mt-5 rounded-xl border border-red-200 bg-red-50 p-4 text-red-800" role="alert">{error}</div>}
        {!loading && !error && messages.length === 0 && searchParams.get("email") && <p className="mt-6 rounded-xl bg-white p-5 text-slate-600">No hay correos para esta dirección.</p>}

        <div className="mt-6 space-y-4">
          {messages.map((message, index) => (
            <article key={message.id} className={`rounded-2xl border bg-white p-6 shadow-sm ${index === 0 ? "border-cyan-500" : "border-slate-200"}`}>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div><p className="text-xs font-semibold uppercase tracking-wide text-slate-500">{index === 0 ? "Más reciente" : "Correo anterior"}</p><h2 className="mt-1 font-bold">{message.subject}</h2></div>
                <time className="text-sm text-slate-500">{new Date(message.created_at).toLocaleString("es-MX")}</time>
              </div>
              <p className="mt-4 text-slate-600">{message.body}</p>
              <div className="mt-5 rounded-xl bg-cyan-50 p-5 text-center">
                <p className="text-xs font-semibold uppercase tracking-widest text-cyan-800">Código OTP</p>
                <p className="mt-1 font-mono text-4xl font-bold tracking-[0.25em] text-cyan-950">{message.code}</p>
              </div>
            </article>
          ))}
        </div>
      </div>
    </main>
  );
}

