import { useEffect, useMemo, useRef, useState } from "react";
import SimulateNewDevice from "../SimulateNewDevice";
import ResumeByEmail from "../ResumeByEmail";
import { formatMexicoDateTime as formatSlot } from "../mexicoTime";
import useAbortableEffect from "../useAbortableEffect";
import BrandLogo from "../ui/BrandLogo";
import { CatalogOptions, PatientFields, StudyOptions } from "../BookingFields";

import {
  cancelWebCase,
  confirmIdentityVerification,
  continueWebCase,
  createNewWebCase,
  getCaseTimeline,
  getClinics,
  getSlots,
  getStudies,
  requestIdentityVerification,
  saveWebDraft,
  sendWebInteraction,
} from "../api";


function draftData(form, studyId) {
  const relationship = form.forWhom === "self" ? "self" : form.relationship;
  return {
    requester: {
      full_name: form.fullName,
      birth_date: form.birthDate,
      email: form.email,
      phone: form.phone,
    },
    relationship,
    patient: relationship === "self"
      ? null
      : {
          full_name: form.patientName,
          birth_date: form.patientBirthDate,
        },
    study_id: studyId,
  };
}

function Progress({ current }) {
  const steps = ["Estudio", "Datos", "Clínica", "Horario", "Confirmación"];
  return (
    <ol className="grid grid-cols-5 gap-2" aria-label="Progreso del trámite">
      {steps.map((step, index) => (
        <li key={step} className="text-center">
          <div className={`mx-auto mb-2 h-2 rounded-full ${index <= current ? "bg-primary" : "bg-line"}`} />
          <span className="hidden text-xs text-muted sm:block">{step}</span>
        </li>
      ))}
    </ol>
  );
}

export default function Web() {
  const [phase, setPhase] = useState("start");
  const [thirdParty, setThirdParty] = useState(false);
  const [studies, setStudies] = useState([]);
  const [clinics, setClinics] = useState([]);
  const [slots, setSlots] = useState([]);
  const [studyId, setStudyId] = useState("");
  const [quote, setQuote] = useState(null);
  const [caseData, setCaseData] = useState(null);
  const [timeline, setTimeline] = useState([]);
  const [previousCases, setPreviousCases] = useState([]);
  const [draftStatus, setDraftStatus] = useState("");
  const [hasDraft, setHasDraft] = useState(false);
  const [cancelledKind, setCancelledKind] = useState(null);
  const [loginEmail, setLoginEmail] = useState("");
  const [otpCode, setOtpCode] = useState("");
  const [verificationInfo, setVerificationInfo] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [form, setForm] = useState({
    fullName: "",
    birthDate: "",
    email: "",
    phone: "",
    forWhom: "self",
    relationship: "hijo_a",
    patientName: "",
    patientBirthDate: "",
  });
  const draftTimerRef = useRef(null);
  const draftRequestRef = useRef(Promise.resolve());

  async function displayCase(activeCase, studyItems = studies, signal) {
    if (activeCase.pending) {
      setCaseData(null);
      setPhase("resume_email");
      return;
    }
    setCaseData(activeCase);
    setStudyId(activeCase.study_id ?? "");
    setQuote(studyItems.find((study) => study.id === activeCase.study_id) ?? null);
    setForm((current) => ({
      ...current,
      fullName: activeCase.requester.full_name ?? "",
      birthDate: activeCase.requester.birth_date ?? "",
      email: activeCase.requester.email ?? "",
      phone: activeCase.requester.phone ?? "",
      forWhom: activeCase.relationship === "self" ? "self" : "other",
      relationship: activeCase.relationship === "self" ? "hijo_a" : activeCase.relationship,
      patientName: activeCase.relationship === "self" ? "" : activeCase.patient.full_name ?? "",
      patientBirthDate: activeCase.relationship === "self" ? "" : activeCase.patient.birth_date ?? "",
    }));
    if (!activeCase.steps.study) {
      setPhase("study");
    } else if (!activeCase.steps.patient_data) {
      setPhase("preregister");
    } else if (!activeCase.steps.clinic) {
      setPhase("clinic");
    } else if (!activeCase.steps.slot) {
      const clinicSlots = await getSlots(activeCase.clinic_id, signal);
      if (signal?.aborted) return;
      setSlots(clinicSlots);
      setPhase("slot");
    } else if (!activeCase.steps.confirmed) {
      setPhase("confirm");
    } else {
      setPhase("done");
    }
  }

  useAbortableEffect((signal) => {
    async function initialize() {
      try {
        const [studyItems, clinicItems, resumed] = await Promise.all([
          getStudies(signal),
          getClinics(signal),
          continueWebCase(signal),
        ]);
        if (signal.aborted) return;
        setStudies(studyItems);
        setClinics(clinicItems);
        setPreviousCases(resumed.previous_cases ?? []);
        if (resumed.draft) {
          const saved = resumed.draft;
          const savedRelationship = saved.relationship ?? "self";
          setStudyId(saved.study_id ?? "");
          setQuote(studyItems.find((study) => study.id === saved.study_id) ?? null);
          setForm((current) => ({
            ...current,
            fullName: saved.requester?.full_name ?? "",
            birthDate: saved.requester?.birth_date ?? "",
            email: saved.requester?.email ?? "",
            phone: saved.requester?.phone ?? "",
            forWhom: savedRelationship === "self" ? "self" : "other",
            relationship: savedRelationship === "self" ? "hijo_a" : savedRelationship,
            patientName: saved.patient?.full_name ?? "",
            patientBirthDate: saved.patient?.birth_date ?? "",
          }));
          setHasDraft(true);
          setDraftStatus("Guardado");
          setPhase(saved.study_id ? "preregister" : "study");
          return;
        }
        if (!resumed.case) return;

        await displayCase(resumed.case, studyItems, signal);
      } catch (reason) {
        if (!signal.aborted) setError(reason.message);
      } finally {
        if (!signal.aborted) setLoading(false);
      }
    }

    initialize();
  }, []);

  function persistDraft(snapshot = form) {
    setDraftStatus("Guardando...");
    const nextRequest = draftRequestRef.current
      .catch(() => undefined)
      .then(() => saveWebDraft(draftData(snapshot, studyId)))
      .then(() => {
        setHasDraft(true);
        setDraftStatus("Guardado");
      })
      .catch((reason) => {
        setDraftStatus("");
        setError(reason.message);
      });
    draftRequestRef.current = nextRequest;
    return nextRequest;
  }

  useEffect(() => {
    if (phase !== "preregister" || thirdParty) return undefined;
    setDraftStatus("Guardando...");
    window.clearTimeout(draftTimerRef.current);
    draftTimerRef.current = window.setTimeout(() => persistDraft(form), 600);
    return () => window.clearTimeout(draftTimerRef.current);
  }, [form, phase, studyId, thirdParty]);

  const currentStep = useMemo(
    () => ({ start: 0, verify_email: 0, verify_code: 0, study: 0, preregister: 1, clinic: 2, slot: 3, confirm: 4, done: 4, cancelled: 4 })[phase] ?? 0,
    [phase],
  );

  function run(task) {
    setLoading(true);
    setError("");
    return task().catch((reason) => setError(reason.message)).finally(() => setLoading(false));
  }

  function updateForm(event) {
    setForm((current) => ({ ...current, [event.target.name]: event.target.value }));
  }

  function flushDraft() {
    if (phase !== "preregister" || thirdParty) return;
    window.clearTimeout(draftTimerRef.current);
    persistDraft(form);
  }

  function startQuote() {
    run(async () => {
      await sendWebInteraction("start_quote");
      setPhase("study");
    });
  }

  function openExistingCase() {
    setPhase("resume_email");
  }

  async function displayResume(result) {
    if (result.case) {
      await displayCase(result.case);
      return;
    }
    const { requester, patient, relationship = "self", study_id: study } = result.draft;
    setCaseData(null);
    setStudyId(study ?? "");
    setQuote(studies.find((item) => item.id === study) ?? null);
    setForm({
      fullName: requester?.full_name ?? "", birthDate: requester?.birth_date ?? "",
      email: requester?.email ?? "", phone: requester?.phone ?? "",
      forWhom: !relationship || relationship === "self" ? "self" : "other",
      relationship: relationship && relationship !== "self" ? relationship : "hijo_a",
      patientName: patient?.full_name ?? "", patientBirthDate: patient?.birth_date ?? "",
    });
    setHasDraft(true);
    setDraftStatus("Guardado");
    setPhase(study ? "preregister" : "study");
  }

  function bookForSomeoneElse() {
    setThirdParty(true);
    setForm((current) => ({ ...current, forWhom: "other", relationship: "hijo_a", patientName: "", patientBirthDate: "" }));
    setCaseData(null);
    setStudyId("");
    setQuote(null);
    setTimeline([]);
    setPhase("study");
  }

  function sendLoginOtp(event) {
    event.preventDefault();
    run(async () => {
      const result = await requestIdentityVerification("web", loginEmail, "email_otp");
      setVerificationInfo(result);
      setOtpCode("");
      setPhase("verify_code");
    });
  }

  function confirmLoginOtp(event) {
    event.preventDefault();
    setLoading(true);
    setError("");
    confirmIdentityVerification("web", loginEmail, otpCode)
      .then(() => continueWebCase())
      .then(async (resumed) => {
        if (!resumed.case || resumed.case.pending) {
          throw new Error("No encontramos un trámite activo para este correo.");
        }
        setPreviousCases(resumed.previous_cases ?? []);
        await displayCase(resumed.case);
      })
      .catch((reason) => {
        let message = reason.message;
        if (reason.attempts_remaining !== undefined) {
          message += ` Intentos restantes: ${reason.attempts_remaining}.`;
        }
        if (reason.error === "otp_expired") message = "El código expiró. Solicita uno nuevo.";
        if (reason.error === "temporarily_locked") message = "La verificación está bloqueada temporalmente. Intenta más tarde.";
        setError(message);
      })
      .finally(() => setLoading(false));
  }

  function selectStudy(event) {
    event.preventDefault();
    if (!studyId) return;
    run(async () => {
      const data = caseData
        ? { case_id: caseData.id, expected_version: caseData.version, study_id: studyId }
        : { study_id: studyId };
      const result = await sendWebInteraction("select_study", data);
      setQuote(result.quote);
      if (result.case) {
        setCaseData(result.case);
        setQuote(studies.find((study) => study.id === studyId) ?? null);
        setPhase(result.case.steps.patient_data ? "clinic" : "preregister");
      } else {
        setPhase("preregister");
      }
    });
  }

  function preregister(event) {
    event.preventDefault();
    run(async () => {
      window.clearTimeout(draftTimerRef.current);
      await draftRequestRef.current;
      const relationship = form.forWhom === "self" ? "self" : form.relationship;
      const data = {
        requester: {
          full_name: form.fullName,
          birth_date: form.birthDate,
          email: form.email,
          phone: form.phone,
        },
        relationship,
        study_id: studyId,
      };
      if (relationship !== "self") {
        data.patient = {
          full_name: form.patientName,
          birth_date: form.patientBirthDate,
        };
      }
      const result = await sendWebInteraction("preregister", data);
      setThirdParty(false);
      setCaseData(result.case);
      setHasDraft(false);
      setDraftStatus("");
      setPhase("clinic");
    });
  }

  function chooseClinic(clinicId) {
    run(async () => {
      const result = await sendWebInteraction("select_clinic", {
        case_id: caseData.id,
        expected_version: caseData.version,
        clinic_id: clinicId,
      });
      const availableSlots = await getSlots(clinicId);
      setCaseData(result.case);
      setSlots(availableSlots);
      setPhase("slot");
    });
  }

  function chooseSlot(slotId) {
    run(async () => {
      const result = await sendWebInteraction("select_slot", {
        case_id: caseData.id,
        expected_version: caseData.version,
        slot_id: slotId,
      });
      setCaseData(result.case);
      setPhase("confirm");
    });
  }

  function confirmCase() {
    run(async () => {
      const result = await sendWebInteraction("confirm_case", {
        case_id: caseData.id,
        expected_version: caseData.version,
      });
      const history = await getCaseTimeline(caseData.id);
      setCaseData(result.case);
      setTimeline(history.events);
      setPhase("done");
    });
  }

  function cancelCurrent() {
    const confirmed = window.confirm(
      caseData
        ? "¿Seguro que deseas cancelar este trámite? Se conservará en la línea de tiempo."
        : "¿Seguro que deseas descartar este borrador?",
    );
    if (!confirmed) return;
    run(async () => {
      window.clearTimeout(draftTimerRef.current);
      await draftRequestRef.current;
      const result = await cancelWebCase(caseData);
      setHasDraft(false);
      setDraftStatus("");
      setCancelledKind(result.case ? "case" : "draft");
      if (result.case) {
        const history = await getCaseTimeline(result.case.id);
        setCaseData(result.case);
        setTimeline(history.events);
      } else {
        setCaseData(null);
      }
      setPhase("cancelled");
    });
  }

  function startNewCase() {
    setCaseData(null);
    setTimeline([]);
    setStudyId("");
    setQuote(null);
    setSlots([]);
    setHasDraft(false);
    setDraftStatus("");
    setCancelledKind(null);
    setForm({
      fullName: "",
      birthDate: "",
      email: "",
      phone: "",
      forWhom: "self",
      relationship: "hijo_a",
      patientName: "",
      patientBirthDate: "",
    });
    startQuote();
  }

  function scheduleAnotherStudy() {
    run(async () => {
      const result = await createNewWebCase(caseData);
      setPreviousCases(result.previous_cases ?? []);
      setCaseData(result.case);
      setTimeline([]);
      setStudyId("");
      setQuote(null);
      setSlots([]);
      setHasDraft(false);
      setDraftStatus("");
      setCancelledKind(null);
      setForm((current) => ({
        ...current,
        fullName: result.case.requester.full_name ?? "",
        birthDate: result.case.requester.birth_date ?? "",
        email: result.case.requester.email ?? "",
        phone: result.case.requester.phone ?? "",
        forWhom: "self",
        relationship: "hijo_a",
        patientName: "",
        patientBirthDate: "",
      }));
      setPhase("study");
    });
  }

  return (
    <main className="min-h-screen bg-page">
      <SimulateNewDevice disabled={loading} />
      <header className="border-b-4 border-brand-yellow bg-surface">
        <div className="mx-auto flex max-w-5xl flex-wrap items-center justify-between gap-3 px-5 py-5">
          <div>
            <BrandLogo />
            <h1 className="text-xl font-bold text-ink">Cotiza y agenda tu estudio</h1>
          </div>
          <span className="rounded-full bg-brand-yellow px-3 py-1 text-xs font-bold text-ink">Datos ficticios</span>
        </div>
      </header>

      <div className="mx-auto max-w-3xl px-5 py-8">
        <Progress current={currentStep} />

        {error && <div className="mt-6 rounded-xl border border-danger-line bg-danger-soft p-4 text-sm text-danger" role="alert">{error}</div>}
        {loading && <div className="mt-6 rounded-xl bg-primary-soft p-4 text-sm text-primary-strong" role="status">Procesando…</div>}

        {(caseData || hasDraft) && phase !== "cancelled" && (
          <div className="mt-5 flex justify-end">
            <button className="text-sm font-semibold text-danger underline-offset-4 hover:underline disabled:opacity-50" disabled={loading} onClick={cancelCurrent}>{phase === "done" ? "Cancelar cita" : "Cancelar trámite"}</button>
          </div>
        )}

        <section className="mt-8 rounded-2xl border border-line bg-surface p-6 shadow-sm sm:p-8">
          {caseData && !caseData.pending && phase !== "cancelled" && (
            <button type="button" className="mb-4 text-sm font-semibold text-primary-strong underline" disabled={loading} onClick={bookForSomeoneElse}>
              Agendar para otra persona
            </button>
          )}
          {phase === "start" && (
            <div className="py-10 text-center">
              <h2 className="text-3xl font-bold">Tu salud, sin empezar de nuevo</h2>
              <p className="mx-auto mt-3 max-w-xl text-muted">Consulta precios ficticios y conserva el avance de tu trámite en esta sesión.</p>
              <div className="mt-8 flex flex-col justify-center gap-3 sm:flex-row">
                <button className="button-primary" disabled={loading} onClick={startQuote}>Comenzar cotización</button>
                <button className="rounded-xl border border-primary px-6 py-3 font-semibold text-primary-strong hover:bg-primary-soft disabled:opacity-50" disabled={loading} onClick={openExistingCase}>Ya tengo un trámite</button>
              </div>
            </div>
          )}

          {phase === "resume_email" && (
            <ResumeByEmail studies={studies} clinics={clinics} onSelected={displayResume} onClose={() => setPhase("start")} />
          )}
          {phase === "verify_email" && (
            <form className="mx-auto max-w-md" onSubmit={sendLoginOtp}>
              <h2 className="section-title">Recupera tu trámite</h2>
              <p className="section-copy">Enviaremos un código al correo registrado. En esta demo podrás consultarlo en el buzón simulado.</p>
              <label className="field mt-6">Correo electrónico<input required type="email" value={loginEmail} onChange={(event) => setLoginEmail(event.target.value)} placeholder="luis.demo@example.com" /></label>
              <button className="button-primary mt-6 w-full" disabled={loading}>Enviar código</button>
            </form>
          )}

          {phase === "verify_code" && (
            <form className="mx-auto max-w-md" onSubmit={confirmLoginOtp}>
              <h2 className="section-title">Escribe el código</h2>
              <p className="section-copy">Lo enviamos a {verificationInfo?.masked_email}. El código vence en cinco minutos.</p>
              <label className="field mt-6">Código de 6 dígitos<input required inputMode="numeric" pattern="[0-9]{6}" maxLength="6" value={otpCode} onChange={(event) => setOtpCode(event.target.value.replace(/\D/g, ""))} placeholder="123456" /></label>
              <a className="mt-3 inline-block text-sm font-semibold text-primary hover:underline" href={`/mailbox?email=${encodeURIComponent(loginEmail)}`}>Abrir buzón simulado</a>
              <button className="button-primary mt-6 w-full" disabled={loading || otpCode.length !== 6}>Verificar y continuar</button>
              <button className="mt-3 w-full text-sm font-semibold text-muted hover:underline" type="button" disabled={loading} onClick={() => setPhase("verify_email")}>Solicitar otro código</button>
            </form>
          )}

          {phase === "study" && (
            <form onSubmit={selectStudy}>
              <h2 className="section-title">Elige un estudio</h2>
              <p className="section-copy">Los precios e indicaciones son únicamente para esta demostración.</p>
              {caseData && (
                <p className="mt-4 rounded-xl bg-primary-soft p-4 text-sm text-primary-strong">
                  Solicitante: <strong>{caseData.requester.full_name}</strong>. Tus datos ya están precargados.
                </p>
              )}
              <StudyOptions studies={studies} studyId={studyId} onSelect={setStudyId} />
              <button className="button-primary mt-6 w-full sm:w-auto" disabled={!studyId || loading}>Cotizar este estudio</button>
            </form>
          )}

          {phase === "preregister" && (
            <form onBlur={flushDraft} onSubmit={preregister}>
              <div className="flex items-center justify-between gap-4">
                <h2 className="section-title">Completa tu preregistro</h2>
                <span className="text-xs font-medium text-muted" aria-live="polite">{draftStatus}</span>
              </div>
              {quote && <div className="mt-4 rounded-xl bg-primary-soft p-4 text-primary-strong"><strong>{quote.name}</strong> · ${quote.price} MXN</div>}
              <div className="mt-6 grid gap-4 sm:grid-cols-2">
                <label className="field sm:col-span-2">Nombre completo<input required readOnly={thirdParty} name="fullName" value={form.fullName} onChange={updateForm} /></label>
                <label className="field">Fecha de nacimiento<input required readOnly={thirdParty} type="date" name="birthDate" value={form.birthDate} onChange={updateForm} /></label>
                <label className="field">Teléfono<input required readOnly={thirdParty} type="tel" name="phone" placeholder="222 123 4567" value={form.phone} onChange={updateForm} /></label>
                <label className="field sm:col-span-2">Correo electrónico<input required readOnly={thirdParty} type="email" name="email" value={form.email} onChange={updateForm} /></label>
                <PatientFields form={form} onChange={updateForm} />
              </div>
              <button className="button-primary mt-6" disabled={loading}>Guardar y continuar</button>
            </form>
          )}

          {phase === "clinic" && (
            <div>
              <h2 className="section-title">Elige una clínica</h2>
              <p className="section-copy">Todas las ubicaciones son ficticias.</p>
              <CatalogOptions items={clinics} disabled={loading} onSelect={chooseClinic} />
            </div>
          )}

          {phase === "slot" && (
            <div>
              <h2 className="section-title">Elige un horario</h2>
              <CatalogOptions items={slots} disabled={loading} onSelect={chooseSlot} slots />
            </div>
          )}

          {phase === "confirm" && caseData && (
            <div>
              <h2 className="section-title">Confirma los datos de tu cita</h2>
              <dl className="mt-6 grid gap-4 rounded-xl bg-page p-5 sm:grid-cols-2">
                <div><dt className="summary-label">Paciente</dt><dd>{caseData.patient.full_name}</dd></div>
                <div><dt className="summary-label">Estudio</dt><dd>{studies.find((item) => item.id === caseData.study_id)?.name}</dd></div>
                <div><dt className="summary-label">Clínica</dt><dd>{clinics.find((item) => item.id === caseData.clinic_id)?.name}</dd></div>
                <div><dt className="summary-label">Horario</dt><dd>{formatSlot(caseData.slot_datetime)}</dd></div>
              </dl>
              <button className="button-primary mt-6" disabled={loading} onClick={confirmCase}>Confirmar cita</button>
            </div>
          )}

          {phase === "done" && caseData && (
            <div className="text-center">
              <div className="mx-auto grid h-14 w-14 place-items-center rounded-full bg-success-soft text-2xl text-success">✓</div>
              <h2 className="mt-4 text-2xl font-bold">Cita confirmada</h2>
              <p className="mt-2 text-muted">Tu folio ficticio es <strong>{caseData.id}</strong>.</p>
              <button className="button-primary mt-6" disabled={loading} onClick={scheduleAnotherStudy}>Agendar otro estudio</button>
              <details className="mt-8 text-left"><summary className="cursor-pointer font-semibold">Ver línea de tiempo</summary><ol className="mt-4 space-y-2 border-l-2 border-primary-soft pl-4">{timeline.map((event) => <li key={event.event_id} className="text-sm text-muted"><time dateTime={event.timestamp}>{formatSlot(event.timestamp)}</time> · {event.type.replaceAll("_", " ")}</li>)}</ol></details>
            </div>
          )}

          {phase === "cancelled" && (
            <div className="py-8 text-center">
              <div className="mx-auto grid h-14 w-14 place-items-center rounded-full bg-subtle text-2xl text-muted">×</div>
              <h2 className="mt-4 text-2xl font-bold">{cancelledKind === "case" ? "Trámite cancelado" : "Borrador descartado"}</h2>
              <p className="mt-2 text-muted">{cancelledKind === "case" ? "El trámite se conserva en tu línea de tiempo." : "Los datos incompletos ya no están guardados."}</p>
              {cancelledKind === "case" && timeline.length > 0 && (
                <details className="mt-6 text-left"><summary className="cursor-pointer font-semibold">Ver línea de tiempo</summary><ol className="mt-4 space-y-2 border-l-2 border-primary-soft pl-4">{timeline.map((event) => <li key={event.event_id} className="text-sm text-muted"><time dateTime={event.timestamp}>{formatSlot(event.timestamp)}</time> · {event.type.replaceAll("_", " ")}</li>)}</ol></details>
              )}
              <button className="button-primary mt-8" disabled={loading} onClick={startNewCase}>Empezar un trámite nuevo</button>
            </div>
          )}

          {previousCases.length > 0 && phase !== "start" && (
            <aside className="mt-8 border-t border-line pt-6 text-left">
              <h3 className="font-semibold text-ink">Trámites anteriores</h3>
              <ul className="mt-3 space-y-2">
                {previousCases.map((previousCase, index) => (
                  <li key={`${previousCase.status}-${previousCase.study_id ?? "sin-estudio"}-${index}`} className="flex items-center justify-between gap-4 rounded-lg bg-page px-4 py-3 text-sm">
                    <span>{studies.find((study) => study.id === previousCase.study_id)?.name ?? "Estudio por elegir"}</span>
                    <span className="font-medium text-muted">{previousCase.status.replaceAll("_", " ")}</span>
                  </li>
                ))}
              </ul>
            </aside>
          )}
        </section>
      </div>
    </main>
  );
}

