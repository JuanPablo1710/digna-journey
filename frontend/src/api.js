const API_URL = import.meta.env.VITE_API_URL ?? "";
const WEB_SESSION_KEY = "salud-digna-demo-web-session";
const WEB_CHANNEL_KEY = import.meta.env.VITE_CHANNEL_KEY_WEB ?? "demo-web-key";
const WHATSAPP_CHANNEL_KEY = import.meta.env.VITE_CHANNEL_KEY_WHATSAPP ?? "demo-whatsapp-key";
const CALLCENTER_CHANNEL_KEY = import.meta.env.VITE_CHANNEL_KEY_CALLCENTER ?? "demo-callcenter-key";

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

async function request(path, options = {}) {
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

function staffRequest(path, method = "GET", data, headers = {}) {
  return request(path, {
    method,
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

export function getAgentContext(personId) {
  return staffRequest(`/agent/patients/${encodeURIComponent(personId)}/context`);
}

export function patchAgentCase(item, fields) {
  return staffRequest(`/cases/${encodeURIComponent(item.id)}`, "PATCH", { expected_version: item.version, fields });
}

export function addAgentNote(caseId, text) {
  return staffRequest(`/agent/cases/${encodeURIComponent(caseId)}/notes`, "POST", { text });
}

export const getAdminDashboard = () => staffRequest("/admin/dashboard");
export const getAdminAudit = () => staffRequest("/admin/audit");
export function getAdminCases(status, channel) {
  const query = new URLSearchParams();
  if (status) query.set("status", status);
  if (channel) query.set("channel", channel);
  return staffRequest(`/admin/cases?${query}`);
}
export const resetAdminDemo = () => staffRequest("/demo/reset", "POST");
export const seedAdminDemo = () => staffRequest("/demo/seed", "POST");

export function openStaffStream({ caseId, cursor, onStatus, onConnect, onEvent, onError }) {
  const controller = new AbortController();
  const token = getStaffSession()?.access_token;
  const query = caseId ? `?case_id=${encodeURIComponent(caseId)}` : "";
  let delay = 500;
  let retryTimer;
  let current;

  async function connect() {
    if (controller.signal.aborted) return;
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
      if (controller.signal.aborted) return;
      if (response.status === 401 || response.status === 403) {
        const body = await response.json().catch(() => null);
        onStatus("disconnected");
        onError(Object.assign(new Error(body?.message ?? "La transmisión dejó de estar disponible."), body, { status: response.status }));
        return;
      }
      if (!response.ok || !response.body) throw new Error("No se pudo conectar.");
      reader = response.body.getReader();
      const decoder = new TextDecoder();
      let pending = "";
      connectedAt = Date.now();
      onStatus("connected");
      onConnect?.();
      while (!controller.signal.aborted) {
        const { value, done } = await reader.read();
        if (done || controller.signal.aborted) break;
        watch();
        pending += decoder.decode(value, { stream: true });
        const blocks = pending.split(/\r?\n\r?\n/);
        pending = blocks.pop();
        for (const block of blocks) {
          if (controller.signal.aborted) break;
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
    }
    if (!controller.signal.aborted) {
      if (connectedAt && Date.now() - connectedAt > 5000) delay = 500;
      onStatus("reconnecting");
      retryTimer = window.setTimeout(connect, delay);
      delay = Math.min(delay * 2, 15000);
    }
  }

  onStatus("reconnecting");
  void connect();
  return () => {
    controller.abort();
    current?.abort();
    window.clearTimeout(retryTimer);
  };
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

export async function getStudies() {
  return request("/catalog/studies");
}

export async function getClinics() {
  return request("/catalog/clinics");
}

export async function getSlots(clinicId) {
  return request(`/catalog/slots?clinic_id=${encodeURIComponent(clinicId)}`);
}

export async function sendWebInteraction(action, data = {}, idempotencyKey = crypto.randomUUID()) {
  return request("/channels/web/interactions", {
    method: "POST",
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

export async function continueWebCase() {
  const result = await sendWebInteraction("continue_case");
  if (result.reset_session) {
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
    headers: { "Content-Type": "application/json" },
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
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ channel, identifier, code }),
  });
  if (result.session_identifier) {
    setWebSession(result.session_identifier);
  }
  return result;
}

export async function getMailbox(email) {
  return request(`/demo/mailbox?email=${encodeURIComponent(email)}`);
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

