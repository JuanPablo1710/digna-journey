const API_URL = import.meta.env.VITE_API_URL ?? "";
const WEB_SESSION_KEY = "salud-digna-demo-web-session";
const WEB_CHANNEL_KEY = import.meta.env.VITE_CHANNEL_KEY_WEB ?? "demo-web-key";
const WHATSAPP_CHANNEL_KEY = import.meta.env.VITE_CHANNEL_KEY_WHATSAPP ?? "demo-whatsapp-key";
const CALLCENTER_CHANNEL_KEY = import.meta.env.VITE_CHANNEL_KEY_CALLCENTER ?? "demo-callcenter-key";
const APP_CHANNEL_KEY = import.meta.env.VITE_CHANNEL_KEY_APP ?? "demo-app-key";
const APP_SESSION_KEY = "salud-digna-app-session";

function getWebSession() {
  let identifier = localStorage.getItem(WEB_SESSION_KEY);
  if (!identifier) {
    identifier = `web-${crypto.randomUUID()}`;
    localStorage.setItem(WEB_SESSION_KEY, identifier);
  }
  return identifier;
}

function resetWebSession() {
  const identifier = `web-${crypto.randomUUID()}`;
  localStorage.setItem(WEB_SESSION_KEY, identifier);
  return identifier;
}

function setWebSession(identifier) {
  localStorage.setItem(WEB_SESSION_KEY, identifier);
}

async function request(path, options = {}, onResponse) {
  const response = await fetch(`${API_URL}${path}`, {
    credentials: "include",
    ...options,
  });
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const error = new Error(body?.message ?? "No fue posible completar la solicitud.");
    if (body) Object.assign(error, body);
    throw error;
  }
  onResponse?.(response);
  return body;
}

export async function getHealth() {
  return request("/health");
}

export async function staffLogin(username, password) {
  const session = await request("/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  sessionStorage.setItem("salud-digna-staff", JSON.stringify(session));
  return session;
}

export function getStaffSession() {
  try {
    return JSON.parse(sessionStorage.getItem("salud-digna-staff"));
  } catch {
    return null;
  }
}

export function staffLogout() {
  sessionStorage.removeItem("salud-digna-staff");
}

export function getSavedCall() {
  try {
    const saved = JSON.parse(sessionStorage.getItem("salud-digna-call"));
    return saved?.token === getStaffSession()?.access_token ? saved.call : null;
  } catch {
    return null;
  }
}

export function lookupForAgent(field, value) {
  const query = new URLSearchParams({ [field]: value });
  return staffRequest(`/agent/lookup?${query}`);
}

function staffRequest(path, method = "GET", data, headers = {}, signal) {
  return request(path, {
    method,
    signal,
    headers: {
      Authorization: `Bearer ${getStaffSession()?.access_token ?? ""}`,
      ...(data === undefined ? {} : { "Content-Type": "application/json" }),
      ...headers,
    },
    ...(data === undefined ? {} : { body: JSON.stringify(data) }),
  });
}

export async function callCenterInteraction(kind, phone, callId) {
  const result = await staffRequest("/channels/callcenter/interactions", "POST", {
    kind,
    identifier: phone || "hidden",
    identifier_type: phone ? "phone" : "session",
    idempotency_key: crypto.randomUUID(),
    timestamp: new Date().toISOString(),
    data: callId ? { call_id: callId } : {},
  }, { "X-Channel-Key": CALLCENTER_CHANNEL_KEY });
  if (kind === "call_started") {
    const displayCall = { ...result, startedAt: Date.now(), incomingNumber: phone };
    sessionStorage.setItem("salud-digna-call", JSON.stringify({ token: getStaffSession()?.access_token, call: displayCall }));
    return displayCall;
  } else {
    sessionStorage.removeItem("salud-digna-call");
  }
  return result;
}

export function verifyForAgent(personId, birthDate, callId) {
  return staffRequest("/agent/verify", "POST", {
    person_id: personId, method: "agent_assisted", birth_date: birthDate, call_id: callId,
  });
}

export function getAgentContext(personId, signal) {
  return staffRequest(`/agent/patients/${encodeURIComponent(personId)}/context`, "GET", undefined, {}, signal);
}

export function patchAgentCase(item, fields) {
  return staffRequest(`/cases/${encodeURIComponent(item.id)}`, "PATCH", { expected_version: item.version, fields });
}

export function addAgentNote(caseId, text) {
  return staffRequest(`/agent/cases/${encodeURIComponent(caseId)}/notes`, "POST", { text });
}

export const getAdminDashboard = (signal) => staffRequest("/admin/dashboard", "GET", undefined, {}, signal);
export const getAdminAudit = (signal) => staffRequest("/admin/audit", "GET", undefined, {}, signal);
export function getAdminCases(status, channel, signal) {
  const query = new URLSearchParams();
  if (status) query.set("status", status);
  if (channel) query.set("channel", channel);
  return staffRequest(`/admin/cases?${query}`, "GET", undefined, {}, signal);
}
export const resetAdminDemo = () => staffRequest("/demo/reset", "POST");
export const seedAdminDemo = () => staffRequest("/demo/seed", "POST");

export function openStaffStream({ caseId, cursor, onStatus, onConnect, onEvent, onError }) {
  const page = typeof document === "undefined" ? null : document;
  const token = getStaffSession()?.access_token;
  const query = caseId ? `?case_id=${encodeURIComponent(caseId)}` : "";
  let delay = 500;
  let retryTimer;
  let current;
  let pageHidden = false;
  let stopped = false;

  const paused = () => pageHidden || page?.visibilityState === "hidden";

  function scheduleReconnect() {
    if (stopped || paused() || current || retryTimer !== undefined) return;
    onStatus("reconnecting");
    retryTimer = window.setTimeout(() => {
      retryTimer = undefined;
      void connect();
    }, delay);
    delay = Math.min(delay * 2, 15000);
  }

  function interrupt() {
    window.clearTimeout(retryTimer);
    retryTimer = undefined;
    const connection = current;
    current = undefined;
    connection?.abort();
  }

  function visibilityChanged() {
    if (paused()) interrupt();
    else scheduleReconnect();
  }

  function onPageHide() {
    pageHidden = true;
    interrupt();
  }

  function onPageShow() {
    pageHidden = false;
    visibilityChanged();
  }

  function stop() {
    stopped = true;
    interrupt();
    page?.removeEventListener("visibilitychange", visibilityChanged);
    window.removeEventListener?.("pagehide", onPageHide);
    window.removeEventListener?.("pageshow", onPageShow);
  }

  async function connect() {
    if (stopped || paused() || current || retryTimer !== undefined) return;
    current = new AbortController();
    const connection = current;
    let reader;
    let timeout;
    let connectedAt;
    const release = () => {
      window.clearTimeout(timeout);
      void reader?.cancel().catch(() => {});
    };
    connection.signal.addEventListener("abort", release, { once: true });
    const watch = () => {
      window.clearTimeout(timeout);
      timeout = window.setTimeout(() => connection.abort(), 25000);
    };
    try {
      watch();
      const headers = { Accept: "text/event-stream", Authorization: `Bearer ${token ?? ""}` };
      if (cursor != null) headers["Last-Event-ID"] = String(cursor);
      const response = await fetch(`${API_URL}/stream${query}`, { headers, signal: connection.signal });
      if (connection.signal.aborted) return;
      if (response.status === 401 || response.status === 403) {
        const body = await response.json().catch(() => null);
        if (connection.signal.aborted) return;
        stop();
        onStatus("disconnected");
        onError?.(Object.assign(new Error(body?.message ?? "La transmisión dejó de estar disponible."), body, { status: response.status }));
        return;
      }
      if (!response.ok || !response.body) throw new Error("No se pudo conectar.");
      reader = response.body.getReader();
      const decoder = new TextDecoder();
      let pending = "";
      connectedAt = Date.now();
      onStatus("connected");
      onConnect?.();
      while (!connection.signal.aborted) {
        const { value, done } = await reader.read();
        if (done || connection.signal.aborted) break;
        watch();
        pending += decoder.decode(value, { stream: true });
        const blocks = pending.split(/\r?\n\r?\n/);
        pending = blocks.pop();
        for (const block of blocks) {
          if (connection.signal.aborted) break;
          const lines = block.split(/\r?\n/);
          const id = lines.find((line) => line.startsWith("id:"))?.slice(3).trim();
          const data = lines.filter((line) => line.startsWith("data:")).map((line) => line.slice(5).trimStart()).join("\n");
          if (id == null) continue;
          if (!data) {
            if (cursor == null) cursor = Number(id);
            continue;
          }
          if (Number(id) <= (cursor ?? 0)) continue;
          const event = JSON.parse(data);
          cursor = Number(id);
          delay = 500;
          onEvent(event, cursor);
        }
      }
    } catch {
      // Transport errors and interrupted connections use the same backoff.
    } finally {
      connection.abort();
      if (current === connection) {
        current = undefined;
        if (connectedAt && Date.now() - connectedAt > 5000) delay = 500;
        scheduleReconnect();
      }
    }
  }

  onStatus("reconnecting");
  page?.addEventListener("visibilitychange", visibilityChanged);
  window.addEventListener?.("pagehide", onPageHide);
  window.addEventListener?.("pageshow", onPageShow);
  queueMicrotask(() => void connect());
  return stop;
}

export async function canSimulateNewDevice(signal) {
  await request("/demo/new-device", { signal });
  return true;
}

export async function requestResume(email, phone) {
  return request("/resume/request", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(phone ? { "X-Channel-Key": WHATSAPP_CHANNEL_KEY } : {}),
    },
    body: JSON.stringify({ channel: phone ? "whatsapp" : "web", email, phone }),
  });
}

function resumePost(path, data) {
  return request(`/resume/${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

export function confirmResume(challengeId, code) {
  return resumePost("confirm", { challenge_id: challengeId, code });
}

export async function selectResume(challengeId, item, key) {
  const result = await resumePost("select", {
    challenge_id: challengeId, kind: item.kind, id: item.id,
    expected_version: item.version, idempotency_key: key,
  });
  if (result.session_identifier) setWebSession(result.session_identifier);
  return result;
}

export async function simulateNewDevice() {
  await request("/demo/new-device", { method: "POST" });
  localStorage.clear();
  sessionStorage.clear();
  window.location.reload();
}

export async function getStudies(signal) {
  return request("/catalog/studies", { signal });
}

export async function getClinics(signal) {
  return request("/catalog/clinics", { signal });
}

export async function getSlots(clinicId, signal) {
  return request(`/catalog/slots?clinic_id=${encodeURIComponent(clinicId)}`, { signal });
}

export async function sendWebInteraction(action, data = {}, idempotencyKey = crypto.randomUUID(), signal) {
  return request("/channels/web/interactions", {
    method: "POST",
    signal,
    headers: {
      "Content-Type": "application/json",
      "X-Channel-Key": WEB_CHANNEL_KEY,
    },
    body: JSON.stringify({
      identifier: getWebSession(),
      identifier_type: "session",
      idempotency_key: idempotencyKey,
      kind: "action",
      action,
      content: null,
      data,
      timestamp: new Date().toISOString(),
    }),
  });
}

export async function continueWebCase(signal) {
  const result = await sendWebInteraction("continue_case", undefined, undefined, signal);
  if (result.reset_session && !signal?.aborted) {
    resetWebSession();
  }
  return result;
}

export async function saveWebDraft(draft) {
  return sendWebInteraction("save_draft", draft);
}

export async function cancelWebCase(caseData = null) {
  const data = caseData
    ? { case_id: caseData.id, expected_version: caseData.version }
    : {};
  return sendWebInteraction("cancel_case", data);
}

export async function createNewWebCase(caseData) {
  return sendWebInteraction("new_case", {
    case_id: caseData.id,
    expected_version: caseData.version,
  });
}

export async function requestIdentityVerification(channel, identifier, method, birthDate = null) {
  return request("/identity/verify/request", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(channel === "app" ? { "X-Channel-Key": APP_CHANNEL_KEY } : {}) },
    body: JSON.stringify({
      channel,
      identifier,
      method,
      ...(birthDate ? { birth_date: birthDate } : {}),
    }),
  });
}

export async function confirmIdentityVerification(channel, identifier, code) {
  const result = await request("/identity/verify/confirm", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(channel === "app" ? { "X-Channel-Key": APP_CHANNEL_KEY } : {}) },
    body: JSON.stringify({ channel, identifier, code }),
  });
  if (result.session_identifier) {
    setWebSession(result.session_identifier);
  }
  return result;
}

export const requestAppCode = (email) => requestIdentityVerification("app", email, "email_otp");

export async function loginApp(email, code) {
  const { access_token, valid_until } = await confirmIdentityVerification("app", email, code);
  const session = { access_token, valid_until, email: email.trim().toLowerCase() };
  sessionStorage.setItem(APP_SESSION_KEY, JSON.stringify(session));
  return session;
}

export function getAppSession({ includeExpired = false } = {}) {
  try {
    const saved = JSON.parse(sessionStorage.getItem(APP_SESSION_KEY));
    return saved && (includeExpired || Date.parse(saved.valid_until) > Date.now()) ? saved : null;
  } catch {
    return null;
  }
}

export function logoutApp() {
  sessionStorage.removeItem(APP_SESSION_KEY);
}

function appHeaders(session) {
  return { Authorization: `Bearer ${session.access_token}`, "X-Channel-Key": APP_CHANNEL_KEY };
}

function appRequest(path, session, options, onRenew) {
  return request(path, {
    ...options, headers: { ...appHeaders(session), ...options.headers },
  }, (response) => {
    const validUntil = response.headers.get("X-App-Valid-Until");
    if (!validUntil) return;
    const stored = getAppSession({ includeExpired: true });
    if (stored?.access_token !== session.access_token) return;
    if (Date.parse(validUntil) >= Date.parse(stored.valid_until)) {
      sessionStorage.setItem(APP_SESSION_KEY, JSON.stringify({ ...stored, valid_until: validUntil }));
      onRenew?.(validUntil);
    }
  });
}

export function listAppCases(session, signal, onRenew) {
  return appRequest("/me/cases", session, { signal }, onRenew);
}

export function sendAppInteraction(session, action, data, onRenew) {
  return appRequest("/channels/app/interactions", session, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      identifier: session.email, identifier_type: "account", kind: "action", action,
      idempotency_key: crypto.randomUUID(), timestamp: new Date().toISOString(),
      data,
    }),
  }, onRenew);
}

export async function getMailbox(email, signal) {
  return request(`/demo/mailbox?email=${encodeURIComponent(email)}`, { signal });
}

export async function getCase(caseId) {
  return request(`/cases/${encodeURIComponent(caseId)}`);
}

export async function getCaseTimeline(caseId) {
  return request(`/cases/${encodeURIComponent(caseId)}/timeline`);
}

export async function sendWhatsAppInteraction({
  phone,
  content = null,
  action = null,
  data = {},
  idempotencyKey = crypto.randomUUID(),
}) {
  return request("/channels/whatsapp/interactions", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Channel-Key": WHATSAPP_CHANNEL_KEY,
    },
    body: JSON.stringify({
      identifier: phone,
      identifier_type: "phone",
      idempotency_key: idempotencyKey,
      kind: action ? "action" : "message",
      action,
      content,
      data,
      timestamp: new Date().toISOString(),
    }),
  });
}

export async function resetWhatsAppConversation(phone) {
  return sendWhatsAppInteraction({ phone, action: "reset_conversation" });
}

