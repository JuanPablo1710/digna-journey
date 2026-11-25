import { useEffect, useRef, useState } from "react";
import {
  canSimulateNewDevice, getAppSession, getClinics, getStudies, listAppCases,
  loginApp, logoutApp, openAppCase, requestAppCode,
} from "../api";
import { formatMexicoDateTime } from "../mexicoTime";
import useAbortableEffect from "../useAbortableEffect";
import { Button, Card, ChannelTag, ChatBubble, StatusTag, Table } from "../ui/components";

const steps = {
  study: "Estudio elegido", patient_data: "Datos del paciente", clinic: "Clínica elegida",
  slot: "Horario elegido", confirmed: "Cita confirmada",
};
const relationships = { hijo_a: "Hijo o hija", madre_padre: "Madre o padre", pareja: "Pareja", otro: "Otro parentesco" };

export default function App() {
  const [session, setSession] = useState(getAppSession);
  const currentSession = useRef(session);
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [challenge, setChallenge] = useState(null);
  const [items, setItems] = useState([]);
  const [opened, setOpened] = useState(null);
  const [catalog, setCatalog] = useState({ studies: [], clinics: [] });
  const [demo, setDemo] = useState(false);
  const [busy, setBusy] = useState(false);
  const [listing, setListing] = useState(false);
  const [error, setError] = useState("");

  useAbortableEffect((signal) => {
    canSimulateNewDevice(signal).then((visible) => {
      if (!signal.aborted) setDemo(visible);
    }).catch(() => {});
  }, []);

  useEffect(() => {
    if (!session) return;
    const expiry = window.setTimeout(() => {
      endSession("La sesión venció. Solicita otro código.");
    }, Math.max(0, new Date(session.valid_until).getTime() - Date.now()));
    return () => window.clearTimeout(expiry);
  }, [session]);

  useAbortableEffect((signal) => {
    if (!session) return;
    setListing(true);
    Promise.all([listAppCases(session, signal), getStudies(signal), getClinics(signal)]).then(([result, studies, clinics]) => {
      if (!signal.aborted) {
        setItems(result.cases);
        setCatalog({ studies, clinics });
      }
    }).catch((reason) => { if (!signal.aborted) showError(reason); }).finally(() => {
      if (!signal.aborted) setListing(false);
    });
  }, [session]);

  function endSession(message = "") {
    logoutApp();
    currentSession.current = null;
    setSession(null);
    setItems([]);
    setOpened(null);
    setChallenge(null);
    setCode("");
    setError(message);
  }

  function showError(reason) {
    if (reason.error === "session_expired" || reason.error === "invalid_token") {
      endSession(reason.message);
      return;
    }
    const attempts = reason.attempts_remaining;
    const suffix = attempts != null ? ` Intentos restantes: ${attempts}.` : "";
    setError(reason.message + suffix);
    if (reason.error === "version_conflict" && reason.case) {
      setItems((current) => current.map((item) => item.id === reason.case.id ? reason.case : item));
    }
  }

  async function run(task) {
    setError("");
    setBusy(true);
    try {
      await task();
    } catch (reason) {
      showError(reason);
    } finally {
      setBusy(false);
    }
  }

  function submit(event) {
    event.preventDefault();
    run(async () => {
      if (!challenge) {
        setChallenge(await requestAppCode(email));
      } else {
        const verified = await loginApp(email, code);
        setCode("");
        setChallenge(null);
        currentSession.current = verified;
        setSession(verified);
      }
    });
  }

  function open(item) {
    run(async () => {
      const detail = await openAppCase(session, item);
      if (currentSession.current !== session) return;
      setItems((current) => current.map((row) => row.id === item.id ? detail.case : row));
      setOpened(detail);
    });
  }

  return (
    <main className="app-theme">
      <div className="app-phone">
        <header>
          <h1>{session ? "Mis trámites" : "Salud Digna · App"}</h1>
          {session && <Button secondary disabled={busy} onClick={() => endSession()}>Cerrar sesión</Button>}
        </header>
        <div className="app-body">
          {error && <p role="alert" className="app-bubble app-error">{error}</p>}
          {session ? (
            <>
              {listing && <p role="status">Cargando trámites…</p>}
              {!listing && !items.length && !error && <ChatBubble>No hay trámites para esta cuenta.</ChatBubble>}
              {opened ? (
                <>
                  <Button secondary onClick={() => setOpened(null)}>Volver a mis trámites</Button>
                  <CaseCard item={opened.case} catalog={catalog} />
                  <Card>
                    <h2>Línea de tiempo</h2>
                    <ol className="app-timeline">
                      {opened.timeline.map((event, index) => (
                        <li key={`${event.type}-${index}`}>
                          <ChannelTag channel={event.channel} /> {event.summary}
                          <div className="app-muted"><time dateTime={event.timestamp}>{formatMexicoDateTime(event.timestamp)}</time></div>
                        </li>
                      ))}
                    </ol>
                  </Card>
                </>
              ) : items.map((item) => <CaseCard key={item.id} item={item} catalog={catalog}
                onOpen={() => open(item)} busy={busy} />)}
              {busy && <p role="status">Abriendo trámite…</p>}
            </>
          ) : (
            <Card>
              <h2>Iniciar sesión</h2>
              <ChatBubble>{challenge
                ? `Enviamos un código a ${challenge.masked_email}. Es válido por cinco minutos.`
                : "Usa el correo del solicitante para consultar sus trámites."}</ChatBubble>
              <form className="app-stack" onSubmit={submit}>
                {challenge ? (
                  <label>Código de seis dígitos
                    <input type="password" inputMode="numeric" autoComplete="one-time-code" required
                      pattern="[0-9]{6}" maxLength={6} value={code} onChange={(event) => setCode(event.target.value)} />
                  </label>
                ) : (
                  <label>Correo electrónico
                    <input type="email" autoComplete="email" required value={email} onChange={(event) => setEmail(event.target.value)} />
                  </label>
                )}
                <Button type="submit" disabled={busy}>{busy ? "Procesando…" : challenge ? "Verificar código" : "Enviar código"}</Button>
              </form>
              {challenge && demo && <a target="_blank" rel="noreferrer" href={`/mailbox?email=${encodeURIComponent(email.trim())}`}>Abrir buzón de demo</a>}
              {challenge && <Button secondary disabled={busy} onClick={() => {
                setChallenge(null); setCode(""); setError("");
              }}>Volver al correo</Button>}
            </Card>
          )}
        </div>
      </div>
    </main>
  );
}

function CaseCard({ item, catalog, onOpen, busy }) {
  const rows = [
    ["Estudio", catalog.studies.find((study) => study.id === item.study_id)?.name ?? "Por elegir"],
    ["Clínica", catalog.clinics.find((clinic) => clinic.id === item.clinic_id)?.name ?? "Por elegir"],
    ["Horario (CDMX)", item.slot_datetime ? formatMexicoDateTime(item.slot_datetime) : "Por elegir"],
  ];
  if (item.relationship !== "self") {
    rows.push(["Paciente", item.patient_name ?? "Sin nombre registrado"],
      ["Parentesco", relationships[item.relationship] ?? "Otro"]);
  }
  return (
    <Card>
      <h2>Folio {item.id}</h2>
      <div className="app-tags"><StatusTag status={item.status} /><ChannelTag channel={item.last_channel} /></div>
      <Table rows={rows} label={`Datos del trámite ${item.id}`} />
      <ul className="app-progress" aria-label="Progreso">
        {Object.entries(steps).map(([key, label]) => (
          <li key={key}><span aria-hidden="true">{item.steps[key] ? "✓" : "○"}</span> {label} · {item.steps[key] ? "Completo" : "Pendiente"}</li>
        ))}
      </ul>
      {onOpen && <Button secondary disabled={busy} onClick={onOpen}>Abrir trámite</Button>}
    </Card>
  );
}
