import { useEffect, useRef, useState } from "react";
import {
  canSimulateNewDevice, getAppSession, getClinics, getSlots, getStudies, listAppCases,
  loginApp, logoutApp, requestAppCode, sendAppInteraction,
} from "../api";
import { CatalogOptions, PatientFields, StudyOptions } from "../BookingFields";
import { formatMexicoDateTime } from "../mexicoTime";
import useAbortableEffect from "../useAbortableEffect";
import BrandLogo from "../ui/BrandLogo";
import { Button, Card, ChannelTag, ChatBubble, StatusTag, Table } from "../ui/components";

const steps = {
  study: "Estudio elegido", patient_data: "Datos del paciente", clinic: "Clínica elegida",
  slot: "Horario elegido", confirmed: "Cita confirmada",
};
const relationships = { hijo_a: "Hijo o hija", madre_padre: "Madre o padre", pareja: "Pareja", otro: "Otro parentesco" };

export default function App() {
  const [session, setSession] = useState(getAppSession);
  const currentSession = useRef(session);
  const [validUntil, setValidUntil] = useState(session?.valid_until);
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [challenge, setChallenge] = useState(null);
  const [items, setItems] = useState([]);
  const [opened, setOpened] = useState(null);
  const [creating, setCreating] = useState(false);
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
    if (!session || busy || listing) return;
    const expiry = window.setTimeout(() => {
      endSession("La sesión venció. Solicita otro código.");
    }, Math.max(0, Date.parse(validUntil) - Date.now()));
    return () => window.clearTimeout(expiry);
  }, [session, validUntil, busy, listing]);

  useAbortableEffect((signal) => {
    if (!session) return;
    setListing(true);
    Promise.all([listAppCases(session, signal, setValidUntil), getStudies(signal), getClinics(signal)]).then(([result, studies, clinics]) => {
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
    if (currentSession.current) setEmail(currentSession.current.email);
    currentSession.current = null;
    setSession(null);
    setItems([]);
    setOpened(null);
    setCreating(false);
    setListing(false);
    setChallenge(null);
    setCode("");
    setError(message);
  }

  function showError(reason) {
    if (["session_expired", "invalid_token", "authentication_required"].includes(reason.error)) {
      endSession("Tu sesión venció. Solicita otro código para continuar.");
      return;
    }
    const attempts = reason.attempts_remaining;
    const suffix = attempts != null ? ` Intentos restantes: ${attempts}.` : "";
    setError(reason.message + suffix);
    if (reason.error === "version_conflict" && reason.case) {
      setItems((current) => current.map((item) => item.id === reason.case.id ? reason.case : item));
      setOpened(null);
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
        setValidUntil(verified.valid_until);
        setSession(verified);
      }
    });
  }

  function interact(action, data) {
    run(async () => {
      const detail = await sendAppInteraction(session, action, data, setValidUntil);
      if (currentSession.current !== session) return;
      setItems((current) => [detail.case, ...current.filter((row) => row.id !== detail.case.id)]);
      setCreating(false);
      setOpened(detail);
    });
  }

  function update(action, item, fields) {
    interact(action, { case_id: item.id, expected_version: item.version, ...fields });
  }

  function back() {
    setCreating(false);
    setOpened(null);
    setError("");
  }

  return (
    <main className="app-theme">
      <div className="app-phone">
        <header>
          <BrandLogo />
          <h1>{session ? "Mis trámites" : "Digna Journey · App"}</h1>
          {session && <Button secondary disabled={busy} onClick={() => endSession()}>Cerrar sesión</Button>}
        </header>
        <div className="app-body">
          {error && <p role="alert" className="app-bubble app-error">{error}</p>}
          {session ? (
            <>
              {listing && <p role="status">Cargando trámites…</p>}
              {creating ? (
                <>
                  <Button secondary disabled={busy} onClick={back}>Volver a mis trámites</Button>
                  <NewBooking studies={catalog.studies} busy={busy} onSave={(data) => interact("preregister", data)} />
                </>
              ) : opened ? (
                <>
                  <Button secondary disabled={busy} onClick={back}>Volver a mis trámites</Button>
                  <CaseCard item={opened.case} catalog={catalog} />
                  <BookingStep detail={opened} catalog={catalog} busy={busy}
                    onUpdate={(action, fields) => update(action, opened.case, fields)} />
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
              ) : (
                <>
                  <Button disabled={busy || listing || !catalog.studies.length} onClick={() => {
                    setError(""); setCreating(true);
                  }}>Iniciar un trámite</Button>
                  {!listing && !items.length && !error && <ChatBubble>No hay trámites para esta cuenta.</ChatBubble>}
                  {items.map((item) => <CaseCard key={item.id} item={item} catalog={catalog}
                    onOpen={() => update("continue_case", item)} busy={busy} />)}
                </>
              )}
              {busy && <p role="status">Procesando…</p>}
            </>
          ) : (
            <Card>
              <h2>Iniciar sesión</h2>
              <ChatBubble>{challenge
                ? `Enviamos un código a ${challenge.masked_email}. Es válido por cinco minutos.`
                : "Usa tu correo para consultar y agendar tus estudios."}</ChatBubble>
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

function StudyStep({ studies, selected = "", busy, onSelect, title = "Elige un estudio" }) {
  const [studyId, setStudyId] = useState(selected);
  return (
    <Card>
      <h2>{title}</h2>
      <form className="app-stack" onSubmit={(event) => { event.preventDefault(); onSelect(studyId); }}>
        <fieldset disabled={busy}><StudyOptions studies={studies} studyId={studyId} onSelect={setStudyId} /></fieldset>
        <Button type="submit" disabled={busy || !studyId}>Continuar</Button>
      </form>
    </Card>
  );
}

function NewBooking({ studies, busy, onSave }) {
  const [studyId, setStudyId] = useState("");
  const [form, setForm] = useState({ forWhom: "self", relationship: "hijo_a", patientName: "", patientBirthDate: "" });
  if (!studyId) return <StudyStep studies={studies} busy={busy} onSelect={setStudyId} />;

  function save(event) {
    event.preventDefault();
    const data = { study_id: studyId, relationship: form.forWhom === "self" ? "self" : form.relationship };
    if (data.relationship !== "self") {
      data.patient = { full_name: form.patientName, birth_date: form.patientBirthDate };
    }
    onSave(data);
  }

  return (
    <Card>
      <h2>Completa tu preregistro</h2>
      <p>Usaremos los datos de tu cuenta verificada.</p>
      <form onSubmit={save} className="app-stack">
        <fieldset disabled={busy} className="app-stack">
          <PatientFields form={form} onChange={({ target: { name, value } }) => setForm((previous) => ({ ...previous, [name]: value }))} />
        </fieldset>
        <Button type="submit" disabled={busy}>Guardar y continuar</Button>
        <Button secondary disabled={busy} onClick={() => setStudyId("")}>Cambiar estudio</Button>
      </form>
    </Card>
  );
}

function SlotStep({ clinicId, busy, onSelect }) {
  const [slots, setSlots] = useState(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  useAbortableEffect((signal) => {
    getSlots(clinicId, signal).then((result) => {
      if (!signal.aborted) setSlots(result);
    }).catch((reason) => { if (!signal.aborted) setError(reason.message); });
  }, [clinicId, attempt]);

  return (
    <Card>
      <h2>Elige un horario</h2>
      <p>Hora de Ciudad de México</p>
      {!slots && !error && <p role="status">Cargando horarios…</p>}
      {error && <>
        <p role="alert">{error}</p>
        <Button secondary onClick={() => { setError(""); setAttempt((current) => current + 1); }}>Volver a cargar horarios</Button>
      </>}
      {slots?.length === 0 && <p>No hay horarios disponibles.</p>}
      {slots?.length > 0 && <CatalogOptions items={slots} disabled={busy} onSelect={onSelect} slots stacked />}
    </Card>
  );
}

function BookingStep({ detail, catalog, busy, onUpdate }) {
  const { case: item, missing_steps: pending } = detail;
  if (item.status === "cancelado" || item.status === "cita_confirmada") return null;
  if (pending.includes("study")) {
    return <StudyStep studies={catalog.studies} busy={busy} onSelect={(id) => onUpdate("select_study", { study_id: id })} />;
  }
  if (pending.includes("clinic")) {
    return <Card>
      <h2>Elige una clínica</h2>
      <CatalogOptions items={catalog.clinics} disabled={busy} onSelect={(id) => onUpdate("select_clinic", { clinic_id: id })} stacked />
    </Card>;
  }
  if (pending.includes("slot")) {
    return <SlotStep key={item.clinic_id} clinicId={item.clinic_id} busy={busy}
      onSelect={(id) => onUpdate("select_slot", { slot_id: id })} />;
  }
  return <Card>
    <h2>Confirma los datos de tu cita</h2>
    <Button disabled={busy} onClick={() => onUpdate("confirm_case")}>Confirmar cita</Button>
  </Card>;
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
