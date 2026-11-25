import { useEffect, useRef, useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { formatMexicoDateTime, formatMexicoTime } from "../mexicoTime";
import {
  addAgentNote, callCenterInteraction, getAgentContext, getClinics,
  getSavedCall, getStaffSession, getStudies, lookupForAgent, openStaffStream, patchAgentCase, staffLogout,
  verifyForAgent,
} from "../api";

const channels = { web: "Web", whatsapp: "WhatsApp", callcenter: "Call Center", app: "App" };
const relationships = { hijo_a: "Hijo o hija", madre_padre: "Madre o padre", pareja: "Pareja", otro: "Otro parentesco" };

function duration(seconds) {
  const minutes = String(Math.floor(seconds / 60)).padStart(2, "0");
  return `${minutes}:${String(seconds % 60).padStart(2, "0")}`;
}

function maskedLookup(field, value) {
  if (field === "phone") return `***${value.replace(/\D/g, "").slice(-4)}`;
  const [name, domain] = value.trim().toLowerCase().split("@");
  return `${name[0]}***@${domain}`;
}

function Step({ number, title, active, disabled = false, children }) {
  return (
    <section aria-labelledby={`cc-step-${number}`} aria-current={active ? "step" : undefined}
      className={`rounded-xl border bg-white p-5 ${disabled ? "opacity-60" : ""} ${active ? "border-cyan-700 ring-1 ring-cyan-700" : "border-slate-200"}`}>
      <h2 id={`cc-step-${number}`} className="text-lg font-semibold">{number}. {title}</h2>
      {children}
    </section>
  );
}

export default function CallCenter() {
  const navigate = useNavigate();
  const [field, setField] = useState("phone");
  const [identifier, setIdentifier] = useState("");
  const [matches, setMatches] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [phone, setPhone] = useState("");
  const [call, setCall] = useState(getSavedCall);
  const [endedCall, setEndedCall] = useState(null);
  const [now, setNow] = useState(Date.now);
  const [searchOrigin, setSearchOrigin] = useState(null);
  const [identifying, setIdentifying] = useState(false);
  const [validUntil, setValidUntil] = useState(null);
  const [attempts, setAttempts] = useState(null);
  const [blockedUntil, setBlockedUntil] = useState(null);
  const [selection, setSelection] = useState(null);
  const [birthDate, setBirthDate] = useState("");
  const [verified, setVerified] = useState(null);
  const [context, setContext] = useState(null);
  const [catalog, setCatalog] = useState({ studies: [], clinics: [] });
  const [connection, setConnection] = useState("disconnected");
  const liveStream = useRef(null);

  const allowed = getStaffSession()?.role === "asesor";
  const blockedSeconds = Math.max(0, Math.ceil((blockedUntil - now) / 1000));
  const countdownActive = blockedSeconds > 0;
  const displayedCall = call || endedCall;
  const elapsed = displayedCall?.startedAt ? Math.max(0, Math.floor(
    ((endedCall && !call ? endedCall.endedAt : now) - displayedCall.startedAt) / 1000
  )) : 0;
  const stage = verified ? 4 : selection ? 3 : call || identifying ? 2 : 1;

  useEffect(() => {
    if (!call && !countdownActive) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [call, countdownActive]);

  useEffect(() => {
    if (!allowed) return;
    const controller = new AbortController();
    Promise.all([getStudies(), getClinics()]).then(([studies, clinics]) => {
      if (!controller.signal.aborted) setCatalog({ studies, clinics });
    }).catch((reason) => { if (!controller.signal.aborted) setError(reason.message); });
    return () => controller.abort();
  }, [allowed]);

  useEffect(() => {
    if (!verified) return;
    let active = true;
    let refreshTimer;
    async function refresh() {
      refreshTimer = undefined;
      try {
        const result = await getAgentContext(verified);
        if (active) setContext(result);
      } catch (reason) {
        if (active) {
          setContext(null);
          showError(reason);
          if (reason.error === "verification_required") setVerified(null);
        }
      }
    }
    function scheduleRefresh() {
      if (active && !refreshTimer) refreshTimer = window.setTimeout(refresh, 180);
    }
    const stop = openStaffStream({
      onStatus: setConnection,
      // Refresh on connection to cover the gap after verification.
      onConnect: scheduleRefresh,
      onEvent: scheduleRefresh,
      onError(reason) {
        setContext(null);
        setVerified(null);
        showError(reason);
      },
    });
    liveStream.current = stop;
    const expiryTimer = window.setTimeout(() => {
      stop();
      setContext(null);
      setVerified(null);
      setConnection("disconnected");
      setError("La verificación venció. Valida de nuevo al solicitante para continuar.");
    }, validUntil ? Math.max(0, new Date(validUntil).getTime() - Date.now()) : 0);
    return () => {
      active = false;
      window.clearTimeout(expiryTimer);
      window.clearTimeout(refreshTimer);
      stop();
      liveStream.current = null;
    };
  }, [verified, validUntil]);

  if (!allowed) return <Navigate to="/login" replace />;

  function logout() {
    liveStream.current?.();
    staffLogout();
    navigate("/login", { replace: true });
  }

  function showError(reason) {
    if (reason.error === "invalid_token" || reason.error === "authentication_required") {
      logout();
      return;
    }
    if (reason.attempts_remaining != null) setAttempts(reason.attempts_remaining);
    if (reason.retry_after_seconds != null) {
      const receivedAt = Date.now();
      setNow(receivedAt);
      setBlockedUntil(receivedAt + reason.retry_after_seconds * 1000);
      setError("");
      return;
    }
    setError(reason.message);
  }

  async function run(task) {
    setLoading(true);
    setError("");
    try {
      await task();
    } catch (reason) {
      showError(reason);
    } finally {
      setLoading(false);
    }
  }

  function startCall(event) {
    event.preventDefault();
    run(async () => {
      const result = await callCenterInteraction("call_started", phone.trim());
      setNow(Date.now());
      setCall(result);
      setEndedCall(null);
      setSearchOrigin(null);
      setContext(null);
      setVerified(null);
      setSelection(null);
      setMatches(null);
      if (phone.trim()) {
        setField("phone");
        setIdentifier(phone.trim());
        setMatches((await lookupForAgent("phone", phone.trim())).matches);
        setSearchOrigin({ field: "phone", value: phone.trim() });
      }
    });
  }

  function endCall() {
    run(async () => {
      await callCenterInteraction("call_ended", "", call.call_id);
      liveStream.current?.();
      setConnection("disconnected");
      setEndedCall({ ...call, endedAt: Date.now() });
      setCall(null);
      setIdentifying(false);
      setVerified(null);
      setContext(null);
      setSelection(null);
      setMatches(null);
      setBirthDate("");
    });
  }

  function verify(event) {
    event.preventDefault();
    run(async () => {
      const grant = await verifyForAgent(selection.person_id, birthDate, call?.call_id);
      setValidUntil(grant.valid_until);
      setAttempts(3);
      setBlockedUntil(null);
      setBirthDate("");
      const result = await getAgentContext(selection.person_id);
      setVerified(selection.person_id);
      setContext(result);
    });
  }

  function changeCase(item, fields) {
    run(async () => {
      await patchAgentCase(item, fields);
      setContext(await getAgentContext(verified));
    });
  }

  function saveNote(caseId, text) {
    return run(async () => {
      await addAgentNote(caseId, text);
      setContext(await getAgentContext(verified));
    });
  }

  async function search(event) {
    event.preventDefault();
    setLoading(true);
    setError("");
    setMatches(null);
    try {
      const result = await lookupForAgent(field, identifier);
      setMatches(result.matches);
      setSearchOrigin({ field, value: identifier });
    } catch (reason) {
      if (reason.error === "invalid_token" || reason.error === "authentication_required") logout();
      else setError(reason.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="mx-auto max-w-4xl space-y-5 p-5">
      <p className="sticky top-0 z-10 rounded-lg border border-cyan-200 bg-cyan-50 p-3 text-sm text-cyan-950">
        Estás en la vista del asesor. En la llamada real, el paciente habla por teléfono; aquí simulamos la llamada con el botón de llamada entrante.
      </p>
      <header className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Centro de contacto</h1>
        {verified && <span className="rounded bg-slate-100 px-3 py-2 text-sm font-semibold" role="status">
          {connection === "connected" ? "Conectado" : connection === "disconnected" ? "Sin conexión" : "Reconectando..."}
        </span>}
        <button type="button" disabled={loading} onClick={() => run(async () => {
          if (call) await callCenterInteraction("call_ended", "", call.call_id);
          logout();
        })} className="text-sm underline">Cerrar sesión</button>
      </header>
      {error && <p role="alert" className="rounded-lg bg-red-50 p-3 text-red-800">{error}</p>}
      {loading && <p role="status">Procesando…</p>}
      <Step number={1} title="Llamada" active={stage === 1}>
        <div className="mt-3 flex flex-wrap gap-x-5 gap-y-2 text-sm">
          <p>Estado: <strong>{call ? "En llamada" : endedCall ? "Terminada" : "Sin llamada"}</strong></p>
          <p>Cronómetro: <time className="font-mono tabular-nums">{duration(elapsed)}</time></p>
          {displayedCall && <p>{displayedCall.incomingNumber ? `Número entrante: ${displayedCall.incomingNumber}`
            : displayedCall.incomingNumber === "" ? "Número oculto" : "Número no disponible"}</p>}
        </div>
        {call ? (
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <p>{call.trust_level === 1 ? "Llamada activa · Número reconocido" : "Llamada activa · Número oculto o desconocido"}</p>
            <button className="option-button" type="button" disabled={loading} onClick={endCall}>Terminar llamada</button>
          </div>
        ) : (
          <form onSubmit={startCall} className="mt-3 flex flex-wrap items-end gap-3">
            <label className="field">Número entrante
              <input type="tel" value={phone} onChange={(event) => setPhone(event.target.value)} placeholder="Vacío si está oculto" />
            </label>
            <button className="button-primary" disabled={loading}>Llamada entrante</button>
          </form>
        )}
      </Step>
      <Step number={2} title="Identificar" active={stage === 2}>
        <form onSubmit={search} onFocus={() => setIdentifying(true)} className="my-4 flex flex-wrap items-end gap-3">
          <label className="field">Buscar por
            <select value={field} onChange={(event) => { setField(event.target.value); setIdentifier(""); }}>
              <option value="phone">Teléfono</option>
              <option value="email">Correo</option>
            </select>
          </label>
          <label className="field">{field === "phone" ? "Teléfono" : "Correo"}
            <input required type={field === "phone" ? "tel" : "email"} value={identifier} onChange={(event) => setIdentifier(event.target.value)} />
          </label>
          <button className="button-primary" disabled={loading}>{loading ? "Buscando…" : "Buscar"}</button>
        </form>
        {matches?.length === 0 && <p>No hay coincidencias.</p>}
        {matches?.length > 0 && <ul className="space-y-2">{matches.map((person) => (
          <li key={person.person_id} className="space-y-2 rounded-lg border border-slate-200 p-4">
            <p className="font-semibold">{person.masked_name}</p>
            <p className="text-sm text-slate-700">Reconocida · sin verificar</p>
            <p className="text-sm">Correo: {searchOrigin?.field === "email" ? maskedLookup("email", searchOrigin.value) : "No disponible antes de verificar"}</p>
            <p className="text-sm">Teléfono: {searchOrigin?.field === "phone" ? maskedLookup("phone", searchOrigin.value) : "No disponible antes de verificar"}</p>
            <button className="option-button" type="button" disabled={loading} onClick={() => {
              setSelection(person); setBirthDate(""); setVerified(null); setContext(null);
              setAttempts(null); setBlockedUntil(null); setError("");
            }}>Seleccionar esta persona</button>
          </li>
        ))}</ul>}
      </Step>
      <Step number={3} title="Verificar identidad" active={stage === 3} disabled={!selection}>
        {!selection && <p className="mt-2 text-sm">Selecciona una persona para continuar.</p>}
        {verified && validUntil && <p className="mt-2 font-semibold text-emerald-700">
          Verificada · vigente hasta {formatMexicoTime(validUntil)}{call ? " o fin de llamada" : ""}
        </p>}
        {selection && !verified && <>
          <p className="my-2 text-sm">Pide al paciente su fecha de nacimiento y escríbela aquí.</p>
          <p className="my-2 text-sm">{attempts == null
            ? "La verificación permite hasta tres intentos."
            : `Intentos restantes: ${blockedUntil && !blockedSeconds ? 3 : attempts}.`}</p>
          {blockedSeconds > 0 && <p className="my-2 text-sm font-semibold text-red-800" role="status">Verificación bloqueada · Tiempo restante: {duration(blockedSeconds)}.</p>}
          <form onSubmit={verify} className="flex flex-wrap items-end gap-3">
            <label className="field">Fecha de nacimiento de {selection.masked_name}
              <input required type="date" value={birthDate} onChange={(event) => setBirthDate(event.target.value)} disabled={blockedSeconds > 0} />
            </label>
            <button className="button-primary" disabled={loading || blockedSeconds > 0}>Verificar</button>
          </form>
        </>}
      </Step>
      <Step number={4} title="Atender" active={stage === 4} disabled={!context}>
      {!context && <p className="mt-2 text-sm">Verifica la identidad para consultar el trámite.</p>}
      {context && (
        <>
          {context.cases.length === 0 && <p>El solicitante no tiene trámites.</p>}
          {context.cases.map((item) => <AgentCase key={item.id} item={item} catalog={catalog}
            loading={loading} onConfirm={() => changeCase(item, { confirmed: true })} onNote={saveNote} />)}
          <section className="rounded-xl bg-white p-5 shadow-sm">
            <h2 className="font-semibold">Línea de tiempo</h2>
            <ol className="mt-3 space-y-2">
              {context.timeline.map((event) => <li key={event.event_id} className="text-sm">
                <time dateTime={event.timestamp}>{formatMexicoDateTime(event.timestamp)}</time>
                {" · "}<span className="rounded bg-slate-100 px-2 py-1 font-medium">{channels[event.channel] ?? event.channel}</span>{" · "}{event.type.replaceAll("_", " ")}
              </li>)}
            </ol>
          </section>
        </>
      )}
      </Step>
    </main>
  );
}

function AgentCase({ item, catalog, loading, onConfirm, onNote }) {
  const [note, setNote] = useState("");
  const steps = { study: "Estudio", patient_data: "Datos del paciente", clinic: "Clínica", slot: "Horario", confirmed: "Confirmación" };
  return (
    <section className="space-y-3 rounded-xl bg-white p-5 shadow-sm">
      <h3 className="font-semibold">Solicitante: {item.requester.full_name} · Paciente: {item.patient.full_name}</h3>
      {item.relationship !== "self" && <p>Parentesco: {relationships[item.relationship] ?? item.relationship}</p>}
      <p>Trámite {item.id} · {item.status.replaceAll("_", " ")}</p>
      <div className="grid gap-2 sm:grid-cols-2">
        <p>Estudio: {catalog.studies.find((entry) => entry.id === item.study_id)?.name ?? "Por elegir"}</p>
        <p>Clínica: {catalog.clinics.find((entry) => entry.id === item.clinic_id)?.name ?? "Por elegir"}</p>
        <p>Horario: {item.slot_datetime ? formatMexicoDateTime(item.slot_datetime) : "Por elegir"} (CDMX)</p>
        <p>Pasos completados: {Object.keys(steps).filter((step) => item.steps[step]).map((step) => steps[step]).join(", ") || "Ninguno"}</p>
        <p>Pasos pendientes: {item.missing_steps.map((step) => steps[step]).join(", ") || "Ninguno"}</p>
      </div>
      <button className="button-primary" type="button" disabled={loading || item.status === "cancelado" ||
        item.missing_steps.length !== 1 || item.missing_steps[0] !== "confirmed"} onClick={onConfirm}>Confirmar cita</button>
      <h3 className="font-semibold">Notas internas</h3>
      <ul>{item.notes.map((entry) => <li key={entry.id} className="whitespace-pre-wrap">{entry.text}</li>)}</ul>
      <form className="flex flex-wrap items-end gap-3" onSubmit={async (event) => {
        event.preventDefault();
        await onNote(item.id, note);
        setNote("");
      }}>
        <label className="field">Nueva nota<textarea required maxLength={2000} value={note} onChange={(event) => setNote(event.target.value)} /></label>
        <button className="option-button" disabled={loading || !note.trim()}>Agregar nota</button>
      </form>
    </section>
  );
}
