import { useEffect, useMemo, useState } from "react";
import SimulateNewDevice from "../SimulateNewDevice";
import BrandLogo from "../ui/BrandLogo";

import { resetWhatsAppConversation, sendWhatsAppInteraction } from "../api";


const demoNumbers = [
  { value: "+522221111111", label: "Luis Demo · +52 222 111 1111" },
  { value: "+522229999999", label: "Marta / Pablo · +52 222 999 9999" },
];

export default function WhatsApp() {
  const [numberOption, setNumberOption] = useState(demoNumbers[0].value);
  const [customNumber, setCustomNumber] = useState("");
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [resumeInput, setResumeInput] = useState(null);
  const [resumeChallenge, setResumeChallenge] = useState(null);
  const phone = useMemo(
    () => (numberOption === "custom" ? customNumber.trim() : numberOption),
    [numberOption, customNumber],
  );

  useEffect(() => {
    setResumeInput(null);
    setResumeChallenge(null);
    setInput("");
  }, [phone]);

  function appendResponse(result) {
    setMessages((current) => [
      ...current,
      ...result.messages.map((message) => ({ ...message, side: "received" })),
    ]);
  }

  async function run(task) {
    if (!phone) return;
    setLoading(true);
    setError("");
    try {
      const result = await task();
      setResumeInput(result.resume_input ?? null);
      if (result.resume_challenge_id) setResumeChallenge(result.resume_challenge_id);
      appendResponse(result);
    } catch (reason) {
      setError(reason.message);
    } finally {
      setLoading(false);
    }
  }

  function sendText(event) {
    event.preventDefault();
    const content = input.trim();
    if (!content || !phone) return;
    if (resumeInput !== "code" && !/^\d{6}$/.test(content)) {
      setMessages((current) => [...current, { side: "sent", text: content, quick_replies: [] }]);
    }
    setInput("");
    const action = { email: "resume_email_value", code: "resume_code" }[resumeInput] ?? null;
    run(() => sendWhatsAppInteraction({ phone, content, action, data: { resume_challenge_id: resumeChallenge } }));
  }

  function chooseReply(reply) {
    setMessages((current) => [...current, { side: "sent", text: reply.label, quick_replies: [] }]);
    run(() => sendWhatsAppInteraction({ phone, action: reply.action, data: { ...reply.payload, resume_challenge_id: resumeChallenge } }));
  }

  function resetConversation() {
    setMessages([]);
    setResumeChallenge(null);
    setResumeInput(null);
    setInput("");
    run(() => resetWhatsAppConversation(phone));
  }

  function changeNumber(event) {
    setNumberOption(event.target.value);
    setMessages([]);
    setError("");
  }

  return (
    <main className="min-h-screen bg-page px-4 py-6 sm:py-10">
      <div className="mx-auto grid max-w-5xl gap-6 lg:grid-cols-[minmax(0,1fr)_390px] lg:items-start">
        <section className="rounded-2xl border border-success-soft bg-surface p-5 shadow-sm sm:p-7">
          <p className="text-xs font-bold uppercase tracking-[0.2em] text-success">Simulador de canal</p>
          <h1 className="mt-2 text-3xl font-bold text-ink">Chat ficticio</h1>
          <p className="mt-3 text-muted">Elige un número de demostración o escribe otro. No se envían mensajes reales.</p>

          <label className="field mt-6">
            Número simulado
            <select value={numberOption} onChange={changeNumber}>
              {demoNumbers.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
              <option value="custom">Otro número…</option>
            </select>
          </label>
          {numberOption === "custom" && (
            <label className="field mt-4">
              Teléfono
              <input type="tel" value={customNumber} onChange={(event) => { setCustomNumber(event.target.value); setMessages([]); }} placeholder="222 123 4567" />
            </label>
          )}

          <div className="mt-5 flex flex-wrap gap-3">
            <button className="rounded-xl border border-brand-gray px-4 py-3 text-sm font-semibold text-muted hover:bg-page disabled:opacity-50" disabled={loading || !phone} onClick={resetConversation}>Reiniciar conversación</button>
          </div>
          <a className="mt-5 inline-block text-sm font-semibold text-success hover:underline" href="/mailbox">Abrir buzón simulado →</a>
          <p className="mt-3 text-xs text-muted">Para Ana creada desde `/web`, selecciona “Otro número” y usa el teléfono de su preregistro.</p>
        </section>

        <section className="mx-auto flex h-[720px] w-full max-w-[390px] flex-col overflow-hidden rounded-[2rem] border-[8px] border-ink bg-subtle shadow-2xl" aria-label="Conversación simulada">
          <header className="on-green flex items-center gap-3 border-b-4 border-brand-yellow bg-primary-strong px-4 py-3">
            <BrandLogo compact />
            <div className="min-w-0 flex-1">
              <h2 className="text-xl font-bold text-on-primary">Digna Journey · Demo</h2>
              <p className="w-fit max-w-full truncate rounded bg-warning-soft px-2 py-0.5 text-xs font-semibold text-ink">{phone || "Elige un número"}</p>
            </div>
          </header>

          <div className="flex-1 space-y-3 overflow-y-auto p-4" aria-live="polite">
            {messages.length === 0 && (
              <div className="rounded-xl bg-surface p-3 text-sm">
                <p>Escribe «hola» para iniciar o retoma un trámite.</p>
              </div>
            )}
            {messages.map((message, index) => (
              <div key={`${message.side}-${index}`} className={`flex ${message.side === "sent" ? "justify-end" : "justify-start"}`}>
                <div className={`max-w-[88%] rounded-2xl px-3 py-2 text-sm shadow-sm ${message.side === "sent" ? "rounded-br-sm bg-success-soft" : "rounded-bl-sm bg-surface"}`}>
                  <p className="whitespace-pre-wrap">{message.text}</p>
                  {message.quick_replies?.length > 0 && (
                    <div className="mt-3 grid gap-2 border-t border-subtle pt-2">
                      {message.quick_replies.map((reply, replyIndex) => (
                        <button key={`${reply.action}-${replyIndex}`} className="rounded-lg px-2 py-1.5 text-left text-sm font-semibold text-success hover:bg-success-soft disabled:opacity-50" disabled={loading} onClick={() => chooseReply(reply)}>{reply.label}</button>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            ))}
            {loading && <div className="w-fit rounded-2xl rounded-bl-sm bg-surface px-3 py-2 text-sm text-muted shadow-sm">Escribiendo…</div>}
            {error && <div className="rounded-xl border border-danger-line bg-danger-soft p-3 text-sm text-danger" role="alert">{error}</div>}
          </div>

          <button type="button" className="self-start px-4 py-2 text-sm font-semibold text-primary-strong" disabled={loading || !phone}
            onClick={() => chooseReply({ label: "Retomar un trámite", action: "resume_menu", payload: {} })}>
            Retomar un trámite
          </button>
          <form className="flex gap-2 bg-subtle p-3" onSubmit={sendText}>
            <input className="min-w-0 flex-1 rounded-full border border-brand-gray bg-surface px-4 py-2 text-sm outline-none focus:border-primary" type={resumeInput === "code" ? "password" : "text"} inputMode={resumeInput === "code" ? "numeric" : undefined} value={input} onChange={(event) => setInput(event.target.value)} disabled={loading || !phone} aria-label="Mensaje" placeholder="Escribe un mensaje" />
            <button className="grid h-10 w-10 place-items-center rounded-full bg-success text-on-primary disabled:opacity-50" disabled={loading || !input.trim() || !phone} aria-label="Enviar">↑</button>
          </form>
          <SimulateNewDevice disabled={loading} />
        </section>
      </div>
    </main>
  );
}

