import { useState } from "react";
import { useSearchParams } from "react-router-dom";

import { getMailbox } from "../api";
import useAbortableEffect from "../useAbortableEffect";
import BrandLogo from "../ui/BrandLogo";


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
    <main className="min-h-screen bg-subtle px-5 py-10">
      <div className="mx-auto max-w-3xl">
        <header className="rounded-2xl border-b-4 border-brand-yellow bg-surface p-5">
          <BrandLogo />
          <p className="mt-2 text-sm font-semibold uppercase tracking-widest text-primary">Buzón de demostración</p>
          <h1 className="mt-1 text-3xl font-bold">Correos simulados</h1>
          <p className="mt-2 text-muted">Solo contiene datos ficticios y está disponible cuando el modo demo está activo.</p>
        </header>

        <form className="mt-8 flex flex-col gap-3 rounded-2xl bg-surface p-5 shadow-sm sm:flex-row" onSubmit={(event) => { event.preventDefault(); loadMailbox(); }}>
          <label className="field flex-1">Correo electrónico<input required type="email" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="luis.demo@example.com" /></label>
          <button className="button-primary self-end" disabled={loading}>{loading ? "Consultando..." : "Consultar buzón"}</button>
        </form>

        {error && <div className="mt-5 rounded-xl border border-danger-line bg-danger-soft p-4 text-danger" role="alert">{error}</div>}
        {!loading && !error && messages.length === 0 && searchParams.get("email") && <p className="mt-6 rounded-xl bg-surface p-5 text-muted">No hay correos para esta dirección.</p>}

        <div className="mt-6 space-y-4">
          {messages.map((message, index) => (
            <article key={message.id} className={`rounded-2xl border bg-surface p-6 shadow-sm ${index === 0 ? "border-primary" : "border-line"}`}>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div><p className="text-xs font-semibold uppercase tracking-wide text-muted">{index === 0 ? "Más reciente" : "Correo anterior"}</p><h2 className="mt-1 font-bold">{message.subject}</h2></div>
                <time className="text-sm text-muted">{new Date(message.created_at).toLocaleString("es-MX")}</time>
              </div>
              <p className="mt-4 text-muted">{message.body}</p>
              <div className="mt-5 rounded-xl bg-primary-soft p-5 text-center">
                <p className="text-xs font-semibold uppercase tracking-widest text-primary-strong">Código OTP</p>
                <p className="mt-1 font-sans text-4xl font-bold tracking-[0.25em] text-primary-strong">{message.code}</p>
              </div>
            </article>
          ))}
        </div>
      </div>
    </main>
  );
}

