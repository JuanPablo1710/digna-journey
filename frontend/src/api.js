const API_URL = import.meta.env.VITE_API_URL ?? "";
const WEB_SESSION_KEY = "salud-digna-demo-web-session";
const WEB_CHANNEL_KEY = import.meta.env.VITE_CHANNEL_KEY_WEB ?? "demo-web-key";
const WHATSAPP_CHANNEL_KEY = import.meta.env.VITE_CHANNEL_KEY_WHATSAPP ?? "demo-whatsapp-key";

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

