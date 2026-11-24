# SPEC.md — Motor de contexto omnicanal (Salud Digna · HackaTec 2026)

> Fuente de verdad del proyecto. Si algo no está aquí, **no lo inventes**: pregunta.
> Idioma: textos de interfaz y mensajes al usuario en **español**; identificadores de código, tablas y endpoints en **inglés**.

---

## 0. Cómo trabajar con este documento (instrucciones para Codex)

1. Construye **una rebanada (slice) a la vez**, en el orden de la sección 15. No avances a la siguiente hasta que la actual cumpla su "definición de terminado".
2. No cambies contratos de API, nombres de tablas ni eventos sin avisar y sin actualizar este archivo.
3. Cada rebanada incluye **pruebas automáticas** (pytest) del comportamiento nuevo.
4. Mantén las fronteras entre módulos (sección 2). Los canales **nunca** acceden a la base de datos ni al `patient_id`: solo hablan con la API.
5. Todo dato es **ficticio**. No integres servicios externos reales.
6. Prioridad absoluta: **estabilidad y repetibilidad de la demo** sobre cantidad de funciones.

---

## 1. Objetivo y alcance

**Problema.** Los canales de Salud Digna (web, app, WhatsApp, centro de contacto) funcionan aislados: el paciente repite datos y reinicia trámites.

**Solución.** Una capa central que (1) **reconoce y verifica** a la persona sin importar el canal, (2) **conserva el avance** del trámite, (3) registra una **línea de tiempo única** de eventos y (4) protege los datos con **roles, verificación escalonada y auditoría**.

**Cuatro pilares del reto:** Identidad · Contexto y estado · Trazabilidad · Seguridad.

**Demo objetivo (caso de Ana).** Web → WhatsApp → Centro de contacto (→ App opcional), sin repetir datos, con tres escenarios de resiliencia (sección 14).

**Fuera de alcance:** integración con servicios reales de Salud Digna, WhatsApp/telefonía reales, pagos, catálogo o agenda reales, IA obligatoria.

---

## 2. Stack y estructura del repositorio

| Capa | Tecnología |
|---|---|
| Backend | Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy 2.x, uvicorn |
| Base de datos | SQLite (archivo `backend/data/app.db`), acceso solo vía ORM (migrable a PostgreSQL) |
| Auth | JWT (PyJWT) para personal y pacientes con sesión; hash de contraseñas con bcrypt |
| Tiempo real | Server-Sent Events (SSE) |
| Frontend | React + Vite (JavaScript) + Tailwind, **una sola app con una ruta por canal** |
| Pruebas | pytest + httpx (TestClient) |

```
/
├── AGENTS.md
├── SPEC.md
├── README.md                  (instalación, credenciales por rol, pasos del demo)
├── .env.example
├── backend/
│   ├── requirements.txt
│   ├── data/                  (SQLite; ignorado por git)
│   ├── app/
│   │   ├── main.py            (FastAPI, CORS, routers)
│   │   ├── config.py          (variables de entorno)
│   │   ├── db.py              (engine, sesión)
│   │   ├── models.py          (tablas)
│   │   ├── schemas.py         (Pydantic)
│   │   ├── security.py        (JWT, hashing, permisos, enmascarado)
│   │   ├── catalog.py         (estudios, clínicas, horarios ficticios)
│   │   └── modules/
│   │       ├── adapters/      (web.py, whatsapp.py, callcenter.py, app.py → "interacción" canónica)
│   │       ├── identity/      (reconocer, verificar, nivel de confianza)
│   │       ├── cases/         (pasos, estado derivado, versión)
│   │       ├── events/        (registro inmutable, línea de tiempo, SSE)
│   │       ├── conversation/  (motor conversacional de WhatsApp)
│   │       ├── agent/         (consola del asesor)
│   │       ├── admin/         (tablero, auditoría)
│   │       └── demo/          (seed, reset, mailbox simulado)
│   └── tests/
├── frontend/
│   └── src/
│       ├── api.js             (cliente de la API; único punto de acceso al backend)
│       └── pages/             (Web, WhatsApp, CallCenter, App, Admin, Mailbox, Login)
└── docs/                      (diagramas, capturas)
```

**Reglas de arquitectura**

- Monolito modular: cada módulo expone funciones/servicios; los módulos no se importan en círculo.
- **Adaptadores** (`modules/adapters`): traducen la entrada de cada canal a una *interacción canónica* y la respuesta canónica al formato de ese canal. El núcleo (identity, cases, events) **no sabe de qué canal viene** la información.
- El estado actual del trámite se **deriva** de sus pasos; los eventos son **inmutables** (nunca UPDATE/DELETE sobre `events`).

---

## 3. Conceptos del dominio

- **Solicitante** vs **paciente.** Solicitante = quien contacta (escribe, llama, navega); paciente = a quien se le hará el estudio. Pueden ser la misma persona (`relationship = "self"`). La identidad que se reconoce y verifica es la del **solicitante**. Un solicitante puede tener varios trámites con pacientes distintos.
- **Reconocer** (buscar un identificador conocido) **≠ verificar** (probar que quien contacta es esa persona). Un teléfono reconocido **no** basta para mostrar datos.
- **Canal ≠ rol.** Canal = por dónde entra la persona (`web`, `whatsapp`, `callcenter`, `app`). Rol = qué puede ver/hacer (`paciente`, `asesor`, `admin`).
- **Regla:** no se verifica a alguien por el mismo medio que se quiere comprobar.

---

## 4. Modelo de datos

IDs: cadenas cortas legibles (`P-0001`, `C-0001`, `evt_...`). Fechas en UTC ISO-8601.

**persons**: `id`, `full_name` (nullable solo mientras `is_provisional = true`), `birth_date` (nullable solo mientras `is_provisional = true`), `email`, `phone` (E.164, normalizado), `is_provisional` (bool; true hasta la primera verificación exitosa), `created_at`. El servicio impide crear o confirmar un trámite y usar como paciente a una persona sin nombre o fecha de nacimiento. En vistas tolerantes a datos incompletos, un nombre nulo se representa como `Contacto sin registrar`.

**channel_identities**: `id`, `person_id` (nullable únicamente mientras la identidad de nivel 0 solo contiene un borrador), `channel`, `identifier`, `identifier_type` (`session|phone|account`), `session_state` (JSON, estado conversacional o borrador), `last_seen_at`. Único (`channel`, `identifier`). `person_id` se asigna al convertir el borrador en un trámite o al reconocer a la persona.

**verifications**: `id`, `person_id`, `channel`, `identifier`, `method` (`email_otp|dob_check|account_login|agent_assisted`), `code_hash`, `status` (`pending|succeeded|failed|expired|locked`), `attempts`, `expires_at` (OTP: 5 min), `valid_until` (tras éxito: 30 min), `created_at`.

**cases** (el trámite): `id`, `requester_id`, `patient_id`, `relationship` (`self|hijo_a|madre_padre|pareja|otro`), `study_id`, `clinic_id`, `slot_id`, `slot_datetime`, `steps` (JSON, ver sección 6), `status`, `abandoned` (bool), `current_channel`, `last_channel`, `version` (int, inicia en 1), `created_at`, `updated_at`.

**events**: `seq` (autoincremental), `event_id`, `type`, `case_id` (nullable), `person_id` (nullable), `channel`, `actor_role`, `actor_id`, `timestamp`, `payload` (JSON), `idempotency_key` (nullable, único).

**users** (acceso con credenciales o sesión): `id`, `username` (o email), `password_hash` (solo personal), `role` (`paciente|asesor|admin`), `person_id` (solo pacientes).

**notes**: `id`, `case_id`, `author_user_id`, `text`, `created_at`.

**drafts**: `id`, `identity_id` (único mientras el canal posee el borrador), `requester_id` (opcional), `email` (normalizado e indexado), `data`, `version`, `updated_at`, `expires_at`. Las escrituras de Web y WhatsApp actualizan el registro junto con su estado de canal. En producción se puede usar un índice sobre un HMAC del correo canónico con clave separada.

**resume_challenges**: `id`, `email`, `channel`, `destination`, `code_hash`, `attempts`, `expires_at`, `locked_until`, `valid_until`, `scope`, `selections`. La solicitud limpia los intentos ya vencidos cuando tampoco existe un bloqueo ni autorización vigente.

**mailbox_messages** (solo demo): `id`, `email`, `subject`, `body`, `code`, `created_at`. Guarda el contenido del correo simulado y el OTP en claro únicamente para `/demo/mailbox` cuando `DEMO_MODE=true`. `code` y `body` nunca se incluyen en eventos, logs ni respuestas normales de la API. `verifications.code_hash` sigue siendo la única copia del código usada para validar.

---

## 5. Reglas de identidad y nivel de confianza

### 5.1 Normalización
- Teléfonos a E.164 (país por defecto México `+52`). Correos en minúsculas. Fecha de nacimiento `YYYY-MM-DD` (la UI acepta DD/MM/AAAA).

### 5.2 Niveles de confianza (por canal/identificador)

| Nivel | Condición | Qué se puede mostrar |
|---|---|---|
| **0 · Desconocido** | Identificador sin persona asociada | Nada de datos personales ni de trámites. Se puede cotizar (información pública del catálogo). |
| **1 · Reconocido** | Identificador ligado a una persona, **sin** verificación vigente | Solo: "hay un trámite pendiente" (sin estudio, clínica ni datos). |
| **2 · Verificado** | Verificación exitosa con `valid_until` vigente | Detalle completo del trámite del solicitante. |

- **Confianza de origen:** la sesión que *creó* los datos (p. ej. la web donde se hizo el preregistro) tiene nivel 2 sobre **esos** trámites mientras dure la sesión (30 min desde la última actividad). Cualquier **otro canal** debe verificar.
- **Caducidad:** el nivel 2 expira a los 30 min (`valid_until`). Las acciones sensibles (confirmar, reagendar, cancelar, ver contexto) exigen nivel 2 vigente.

### 5.3 Reconocimiento
1. Buscar `channel_identities` por (`channel`, `identifier`).
2. Si no existe y el identificador es un teléfono: buscar `persons.phone`. Si hay **una** coincidencia → crear la identidad ligada (nivel 1). Si hay **varias** → estado `ambiguous`: pedir fecha de nacimiento para desambiguar antes de cualquier otra cosa. Si no hay → nivel 0 y se crea una persona provisional con ese teléfono.
3. Si el canal no trae teléfono (web/app), usar correo, o correo + fecha de nacimiento.
4. Solo coincidencia **exacta** (determinista). Nunca fusionar por nombre parecido.

### 5.4 Verificación

| Canal | Método |
|---|---|
| `web` / `app` | `account_login`: correo + código OTP enviado a ese correo (sin contraseña para pacientes) |
| `whatsapp` | `dob_check` (fecha de nacimiento debe coincidir) **y luego** `email_otp` al correo registrado (nunca por el propio WhatsApp) |
| `callcenter` | `agent_assisted`: el asesor valida un dato (fecha de nacimiento) y lo registra; o el paciente dicta un OTP enviado a su correo |

- OTP de 6 dígitos, expira en 5 min, **máximo 3 intentos**; al 3.º fallo: estado `locked` por 10 min y evento `verificacion_fallida` con `payload.locked = true`. Guardar solo el hash.
- Los correos se **simulan**: se guardan en un buzón de demo consultable en `GET /demo/mailbox?email=...` y en la página `/mailbox`. No se envía correo real.

### 5.5 Vinculación y fusión
- Al verificar con éxito, la persona deja de ser provisional (`is_provisional = false`) y se ligan sus identidades de canal. Si existían dos personas provisionales con los mismos datos exactos (teléfono + correo), se **fusionan** (evento `identidad_fusionada`) conservando el trámite más avanzado.

---

## 6. Trámite: pasos, estado, concurrencia, abandono

### 6.1 Pasos (`cases.steps`)
```json
{ "study": false, "patient_data": false, "clinic": false, "slot": false, "confirmed": false }
```
- `study`: hay estudio elegido. `patient_data`: paciente con nombre, fecha de nacimiento y parentesco completos (más correo y teléfono del solicitante). `clinic`, `slot`: elegidos. `confirmed`: cita confirmada.
- **Los pasos pueden completarse en cualquier orden.** El sistema siempre calcula `missing_steps` y los pide en el canal actual (esto resuelve la "información parcial").

### 6.2 Estado derivado (`status`)
```
cancelado        si fue cancelado
cita_confirmada  si confirmed
horario_propuesto si slot
clinica_elegida   si clinic
datos_completos   si patient_data
cotizando         en otro caso (con study elegido o no)
```
`abandoned` es un indicador **aparte** del progreso: se activa tras `ABANDON_MINUTES` sin actividad (config, por defecto 15; ajustable en demo) mediante una tarea periódica, y emite `tramite_abandonado`. No borra datos. Al volver a haber actividad verificada: `abandoned = false` y evento `tramite_reanudado`.

### 6.3 Concurrencia e idempotencia
- Toda escritura sobre un trámite envía `expected_version`. Si no coincide → **409 Conflict** con el trámite actual; el cliente decide. Cada escritura exitosa incrementa `version`.
- Toda interacción entrante lleva `idempotency_key`. Si ya existe en `events`, se devuelve la respuesta original **sin duplicar** eventos ni cambios.

### 6.4 Cambio de canal
Si llega actividad sobre un trámite por un canal distinto de `last_channel`: emitir `canal_cambiado` (payload: `from`, `to`), actualizar `last_channel` y `current_channel`.

En WhatsApp, un número que era desconocido al iniciar la conversación obtiene confianza de origen durante 30 minutos desde su última actividad, exclusivamente sobre los trámites creados en esa misma conversación. Los identificadores de esos trámites se conservan en `channel_identities.session_state`; esta confianza nunca permite consultar trámites preexistentes ni vincula personas por correo o fecha de nacimiento. Al vencer, el número queda en nivel 1 y debe completar `dob_check` y `email_otp`. Un número que ya estaba ligado a una persona al comenzar nunca recibe esta confianza de origen.

### 6.5 Borrador web y autoguardado
- El formulario de preregistro web se guarda como borrador en `channel_identities.session_state`, ligado a la sesión web. Una identidad que solo contiene un borrador permanece en nivel 0 y tiene `person_id = null`.
- La UI guarda al salir de un campo (`blur`) o después de aproximadamente 600 ms sin escribir. No envía una escritura por cada tecla.
- El borrador admite información incompleta. Guardarlo no crea personas, trámites ni eventos.
- Al enviar un preregistro completo, el borrador se convierte mediante el flujo normal en persona y trámite, se asigna `channel_identities.person_id` y se limpia el borrador.
- `continue_case` devuelve el borrador vigente cuando todavía no existe un trámite, para rellenar el formulario y continuar donde se quedó el usuario.
- El borrador tiene la misma vigencia que la confianza de origen web: 30 minutos desde `last_seen_at`. Un borrador vencido no se recupera ni se expone a otra sesión.

### 6.6 Cancelación de trámite web
- `cancel_case` sobre un trámite exige `expected_version`, cambia `status` a `cancelado`, incrementa `version`, limpia cualquier borrador de la sesión y emite `tramite_cancelado` en la misma transacción.
- Se puede cancelar un trámite en cualquier estado, incluida una cita confirmada. El registro y su línea de tiempo se conservan.
- Cancelar con una versión anterior devuelve 409 con la versión actual. Repetir la misma interacción idempotente no cambia de nuevo el trámite ni duplica `tramite_cancelado`.
- Si la sesión solo tiene un borrador, `cancel_case` descarta el borrador sin crear evento.

### 6.7 Nuevo trámite web después de confirmar
- `new_case` exige el `case_id` y `expected_version` del trámite que se está mostrando. Solo se permite sobre una cita confirmada y con confianza de origen o verificación vigente.
- Crea un trámite independiente para el mismo solicitante, inicialmente con `relationship = "self"`, el solicitante también como paciente y el paso `patient_data` completo. Los demás pasos comienzan vacíos y la UI regresa a la elección de estudio con los datos del solicitante precargados.
- El trámite confirmado anterior no cambia de estado, versión ni línea de tiempo. El nuevo trámite inicia en versión 1 y emite `tramite_creado` en su propia línea de tiempo, en la misma transacción.
- Cuando la sesión puede consultar más de un trámite, `continue_case` muestra el creado más recientemente y devuelve los anteriores en una lista breve que solo contiene estado y estudio.

---

## 7. Eventos (catálogo)

Estructura: `event_id, type, case_id, person_id, channel, actor{role,id}, timestamp, payload, idempotency_key`.

| Grupo | Tipos |
|---|---|
| Identidad | `contacto_creado`, `identidad_vinculada`, `verificacion_solicitada`, `verificacion_exitosa`, `verificacion_fallida`, `identidad_fusionada`, `consentimiento_aceptado` |
| Trámite | `tramite_creado`, `estudio_seleccionado`, `datos_paciente_capturados`, `clinica_seleccionada`, `horario_propuesto`, `cita_confirmada`, `cita_reagendada`, `tramite_cancelado`, `tramite_abandonado`, `tramite_reanudado` |
| Canal | `canal_iniciado`, `canal_cambiado`, `mensaje_recibido`, `mensaje_enviado`, `llamada_iniciada`, `llamada_finalizada` |
| Atención y auditoría | `nota_agregada`, `contexto_consultado`, `acceso_denegado` |

Reglas de emisión:
- Cada operación relevante emite su evento **en la misma transacción** que el cambio de estado.
- `contexto_consultado`: cuando un asesor obtiene el contexto de un paciente. `acceso_denegado`: cuando se rechaza un acceso por rol o por falta de verificación (con `payload.reason`).
- `consentimiento_aceptado`: primer contacto del solicitante (aviso de privacidad simulado), con canal y fecha.
- Cada evento publica una versión **enmascarada** por SSE (sección 8.8).

---

## 8. API

Convenciones: JSON; errores `{ "error": "codigo", "message": "texto en español" }`; respuestas 401/403/404/409/422 estándar. Documentación automática en `/docs`.

### 8.1 Autenticación
- `POST /auth/login` `{username, password}` → `{access_token, role, person_id?}` (asesor y admin).
- Pacientes: `POST /identity/verify/request` y `/confirm` con `channel="app"` o `"web"`; al confirmar devuelven JWT con rol `paciente` y `person_id`.

### 8.2 Catálogo (público, ficticio)
- `GET /catalog/studies`, `GET /catalog/clinics`, `GET /catalog/slots?clinic_id=`.

### 8.3 Interacciones de canal (entrada común)
`POST /channels/{channel}/interactions` · cabecera obligatoria `X-Channel-Key: <clave del canal>` (simula la firma de un webhook; claves en `.env`).

Solicitud (formato canónico):
```json
{
  "identifier": "+522221234567",
  "identifier_type": "phone",
  "idempotency_key": "wa-0001",
  "kind": "message",
  "action": null,
  "content": "hola",
  "data": {},
  "timestamp": "2026-11-24T16:00:00Z"
}
```
- `kind`: `message | action | call_started | call_ended`.
- `action` (cuando `kind=action`): `start_quote, start_booking, save_draft, preregister, select_study, select_clinic, select_slot, confirm_case, cancel_case, continue_case, new_case, talk_to_agent, answer, reset_conversation`.

Respuesta:
```json
{
  "trust_level": 1,
  "case": { "...": "vista según nivel; con nivel < 2 solo {id, pending: true}" },
  "missing_steps": ["slot"],
  "messages": [
    { "text": "Hola, ...", "quick_replies": [ { "label": "Continuar", "action": "continue_case", "payload": {} } ] }
  ],
  "events": ["canal_cambiado", "identidad_vinculada"]
}
```

#### 8.3.1 Formatos definidos para Web en S1

En S1, `POST /channels/web/interactions` usa `identifier_type = "session"`. Los datos específicos de cada acción se envían dentro de `data`:

- `start_quote`: `{}`.
- `continue_case`: `{}`.
- `save_draft`: el mismo objeto de `data` que `preregister`, pero todos sus campos son opcionales y pueden estar incompletos.
- `select_study` antes de crear un trámite: `{ "study_id": "ST-001" }`.
- `select_study` sobre un trámite existente: `{ "case_id": "C-0001", "expected_version": 1, "study_id": "ST-001" }`.
- `select_clinic`: `{ "case_id": "C-0001", "expected_version": 1, "clinic_id": "CL-001" }`.
- `select_slot`: `{ "case_id": "C-0001", "expected_version": 2, "slot_id": "SL-..." }`.
- `confirm_case`: `{ "case_id": "C-0001", "expected_version": 3 }`.
- `cancel_case` sobre un trámite: `{ "case_id": "C-0001", "expected_version": 4 }`.
- `cancel_case` cuando solo existe un borrador: `{}`.
- `new_case`: `{ "case_id": "C-0001", "expected_version": 4 }`, donde el trámite indicado tiene una cita confirmada.

El cuerpo de `data` para `preregister` es:

```json
{
  "requester": {
    "full_name": "Ana Demo",
    "birth_date": "1990-05-10",
    "email": "ana.demo@example.com",
    "phone": "+522221234567"
  },
  "relationship": "self",
  "patient": null,
  "study_id": "ST-001"
}
```

- `requester.email` y `requester.phone` son obligatorios en el preregistro.
- Si `relationship = "self"`, `patient` se omite o es `null` y el solicitante también es el paciente.
- Si `relationship != "self"`, `patient` es obligatorio e incluye al menos `full_name` y `birth_date`; `email` y `phone` son opcionales.
- `birth_date` acepta `YYYY-MM-DD`; también se admite `DD/MM/AAAA` en la entrada.

Cuando `select_study` se usa como cotización pública, la respuesta canónica agrega `quote`:

```json
{
  "quote": {
    "id": "ST-001",
    "name": "Biometría hemática",
    "price": 180,
    "preparation": "Ayuno ficticio de 8 horas."
  }
}
```

La confianza de origen de S1 se mantiene con una cookie HTTP-only llamada `web_session`. El backend la establece o renueva con `Max-Age=1800` y `SameSite=Lax`. El cliente web usa `credentials: "include"` y CORS permite credenciales únicamente desde el origen exacto configurado en `FRONTEND_ORIGIN`.

`save_draft` devuelve la respuesta canónica con `case: null`, `events: []` y un campo adicional `draft` con el borrador guardado. No usa la tabla `events`; su idempotencia se conserva en `session_state`.

Al cargar `/web`, el cliente envía `continue_case`. Si la cookie coincide con el `identifier`, sigue vigente y existe un trámite no cancelado, la respuesta incluye ese trámite y sus `missing_steps`; una cita confirmada también se recupera para permitir su cancelación. Si solo existe un borrador vigente, devuelve `case: null`, `draft` con los campos capturados, `trust_level: 0` y `reset_session: false`. Si falta la cookie o está vencida, la respuesta no expone el trámite ni el borrador anterior, devuelve `case: null`, `draft: null`, `trust_level: 0` y `reset_session: true`, y elimina la cookie. Una sesión válida sin trámite ni borrador devuelve `case: null`, `draft: null` y `reset_session: false`.

Cuando hay varios trámites visibles para esa sesión, tanto `continue_case` como `new_case` agregan `previous_cases`. El trámite más reciente va en `case`; la lista incluye como máximo los tres anteriores y cada elemento se limita a `{ "status": "cita_confirmada", "study_id": "ST-001" }`, sin datos personales ni identificadores internos.

#### 8.3.2 Formatos definidos para WhatsApp en S3

`POST /channels/whatsapp/interactions` usa `identifier_type = "phone"`; el adaptador normaliza el teléfono a E.164. Los mensajes de texto usan `kind = "message"`, `action = null` y el texto en `content`. Las respuestas rápidas usan `kind = "action"`, la acción indicada y estos formatos en `data`:

- `start_quote`, `start_booking`, `continue_case`, `new_case`, `talk_to_agent`, `reset_conversation`: `{}`.
- `select_study`: `{ "study_id": "ST-001", "case_id": "C-0001", "expected_version": 1 }`; `case_id` y `expected_version` se omiten durante una cotización pública.
- `select_clinic`: `{ "clinic_id": "CL-001", "case_id": "C-0001", "expected_version": 2 }`.
- `select_slot`: `{ "slot_id": "SL-...", "case_id": "C-0001", "expected_version": 3 }`.
- `answer`: usa `data.value` para responder preguntas conversacionales, por ejemplo `{ "value": "self" }` o `{ "value": "hijo_a" }`.

Cada respuesta conserva la forma canónica de la sección 8.3. Las respuestas rápidas se entregan dentro de `messages[].quick_replies` como `{label, action, payload}`. Con nivel 0 no se incluye información personal ni de trámites; con nivel 1, `case`, si existe, se limita a `{id, pending: true}`; con nivel 2 se usa la vista completa sin exponer `requester_id` ni `patient_id`.

`reset_conversation` solo está disponible cuando `DEMO_MODE=true`. Limpia `channel_identities.session_state`, fija en el momento actual el `valid_until` de las verificaciones vigentes de ese canal e identificador, y devuelve el saludo inicial. No borra ni modifica personas, trámites o eventos existentes. Cuando `DEMO_MODE=false` responde `403 demo_mode_required`.

Para un número desconocido, `start_booking` captura uno por uno los datos indicados en la sección 9. Al completar los datos crea el trámite y después ofrece estudio, clínica y horario mediante respuestas rápidas. No busca ni fusiona por correo o fecha de nacimiento. La confianza de origen descrita en la sección 6.4 se limita a los `case_id` creados por esa conversación.

### 8.4 Identidad
- `POST /identity/verify/request` `{channel, identifier, method, birth_date?}` → crea verificación (OTP al buzón simulado).
- `POST /identity/verify/confirm` `{channel, identifier, code}` → `{trust_level, valid_until, access_token?}`.

Formatos de S2:

- `channel`: `web | app | whatsapp | callcenter`.
- `method`: `email_otp | dob_check`. `agent_assisted` existe en el servicio de identidad, pero su endpoint se agrega en S4.
- Para `web` y `app`, `email_otp` usa el correo normalizado como `identifier`.
- Para `whatsapp`, `dob_check` usa el teléfono normalizado como `identifier` y exige `birth_date`. Solo después de un `dob_check` exitoso se permite solicitar `email_otp` para ese teléfono; el código se envía al correo registrado, nunca al mismo teléfono.

Respuesta de solicitud OTP:

```json
{
  "status": "pending",
  "trust_level": 1,
  "masked_email": "a***@example.com",
  "expires_at": "2026-11-24T16:05:00Z"
}
```

Respuesta de `dob_check` exitoso:

```json
{
  "status": "succeeded",
  "trust_level": 1,
  "next_method": "email_otp",
  "masked_email": "a***@example.com"
}
```

La confirmación incorrecta devuelve un error con `attempts_remaining`. Al tercer fallo devuelve estado `locked` y `locked_until`; después de diez minutos se puede solicitar un OTP nuevo. Un OTP vencido devuelve `otp_expired` y no sube el nivel de confianza.

En web, la solicitud usa la cookie `web_session` existente. Al confirmar correctamente, el backend crea un nuevo identificador de sesión, vincula esa nueva identidad con la persona, crea una verificación vigente para el nuevo identificador, establece una nueva cookie `web_session`, devuelve el identificador nuevo en `session_identifier` para sincronizar el cliente y elimina la validez de la identidad anterior. La verificación solo permite acceder a trámites cuyo `requester_id` corresponde a esa persona. La persona provisional del navegador solo se fusiona si teléfono y correo coinciden exactamente.

### 8.5 Trámites
- `GET /cases/{id}` → según rol y nivel de confianza (sección 10).
- `PATCH /cases/{id}` `{expected_version, fields}` → actualiza pasos/campos (409 si hay conflicto).
- `GET /me/cases` (paciente con JWT).
- `GET /cases/{id}/timeline` → eventos del trámite en orden cronológico (paciente: versión simple; asesor: completa).

En S1, la sesión web de origen obtiene esta forma de respuesta de `GET /cases/{id}`:

```json
{
  "trust_level": 2,
  "case": {
    "id": "C-0001",
    "relationship": "self",
    "requester": {
      "full_name": "Ana Demo",
      "birth_date": "1990-05-10",
      "email": "ana.demo@example.com",
      "phone": "+522221234567"
    },
    "patient": {
      "full_name": "Ana Demo",
      "birth_date": "1990-05-10",
      "email": "ana.demo@example.com",
      "phone": "+522221234567"
    },
    "study_id": "ST-001",
    "clinic_id": "CL-001",
    "slot_id": null,
    "slot_datetime": null,
    "steps": {
      "study": true,
      "patient_data": true,
      "clinic": true,
      "slot": false,
      "confirmed": false
    },
    "status": "clinica_elegida",
    "abandoned": false,
    "current_channel": "web",
    "last_channel": "web",
    "version": 2,
    "created_at": "2026-11-24T16:00:00Z",
    "updated_at": "2026-11-24T16:05:00Z"
  },
  "missing_steps": ["slot", "confirmed"]
}
```

Los identificadores internos `requester_id` y `patient_id` no se exponen al frontend. La cookie `web_session` vigente es obligatoria para consultar el trámite.

En S1, `GET /cases/{id}/timeline` devuelve:

```json
{
  "events": [
    {
      "event_id": "evt_...",
      "type": "clinica_seleccionada",
      "channel": "web",
      "timestamp": "2026-11-24T16:05:00Z",
      "payload": { "clinic_id": "CL-001" }
    }
  ]
}
```

Los eventos se ordenan por `seq` en orden cronológico. Esta vista simple no expone `person_id`, `actor_id`, `idempotency_key` ni datos internos usados para reconstruir una respuesta idempotente.

#### Retoma por correo

- `POST /resume/request` recibe `{channel, email, phone?}`. WhatsApp requiere teléfono simulado y `X-Channel-Key`. Devuelve 202 con `{challenge_id, message}` y la misma frase para coincidencias y búsquedas sin resultado. El envío simulado ocurre después de responder. La cookie HTTP-only vincula el intento al navegador. El mismo correo y destino reutilizan un intento pendiente.
- `POST /resume/confirm` recibe `{challenge_id, code}`. El código dura cinco minutos, hay tres intentos y el tercer fallo bloquea diez minutos. Tras acertar devuelve `{items}` con `kind, id, version, study_id, clinic_id, status, channel, updated_at`. Un correo compartido permite retomar borradores de ese correo exacto. Los trámites requieren una coincidencia única de solicitante. La autorización dura 30 minutos.
- `POST /resume/select` recibe `{challenge_id, kind, id, expected_version, idempotency_key}`. Devuelve `{case}` o `{draft}` y, en Web, `session_identifier`. Una selección repetida con la misma clave no vuelve a escribir. La transferencia del borrador quita el acceso en el canal anterior y cambia su versión en la misma transacción. Un destino que ya tiene un borrador devuelve 409. En WhatsApp las interacciones posteriores usan `data.resume_challenge_id` con la misma cookie y número. Una identidad existente ligada a otra persona conserva ese vínculo.
- La lista verificada incluye `relationship` y `patient_name`. Un trámite para otra persona captura nombre, fecha de nacimiento y parentesco del paciente tras mostrar el aviso de privacidad simulado. La persona creada para actuar únicamente como paciente carece de correo, teléfono e identidad de canal. La verificación y el alcance de acceso corresponden al solicitante.
- En el chat de WhatsApp, `resume_menu` ofrece `resume_email`. El adaptador recibe el correo en `content` con la acción `resume_email_value` y devuelve `resume_input: "code"` y `resume_challenge_id`. `resume_code` recibe el código en `content` y el identificador del intento en `data.resume_challenge_id`. Tras verificar, `resume_select` aparece como respuesta rápida para cada elemento y usa el mismo identificador en `data`. El código no forma parte del historial del chat ni de los eventos.
- La retoma dentro de la sesión de origen conserva su vigencia de 30 minutos. Los eventos del flujo por correo registran métodos, resultados y referencias opacas.

### 8.6 Asesor (rol `asesor`)
- `GET /agent/lookup?phone=|email=` → coincidencias (solo nombre enmascarado y nivel 1).
- `POST /agent/verify` `{person_id, method:"agent_assisted", birth_date}` → verificación asistida.
- `GET /agent/patients/{person_id}/context` → contexto completo + línea de tiempo. **Requiere verificación vigente**; si no → 403 + evento `acceso_denegado`. Si procede → evento `contexto_consultado`.
- `POST /agent/cases/{id}/notes` `{text}` → `nota_agregada`.
- Confirmar o avanzar el trámite: `PATCH /cases/{id}`.

### 8.7 Administrador (rol `admin`)
- `GET /admin/dashboard` → totales por estado, abandonados, **recuperados entre canales** (trámites con ≥ 2 canales distintos que avanzaron tras `canal_cambiado`), recorrido de canales por trámite, últimos eventos (enmascarados).
- `GET /admin/cases` (enmascarado), `GET /admin/audit` (`contexto_consultado`, `acceso_denegado`, `verificacion_*`).

### 8.8 Tiempo real
- `GET /stream?token=` (SSE). Mensajes `{type, case_id, channel, timestamp, summary}` con datos **enmascarados**. El asesor recibe además actualizaciones del trámite que tiene abierto.

### 8.9 Demo y salud
- Con `DEMO_MODE=true`, `GET /demo/new-device` devuelve 204 e indica que se puede mostrar «Simular otro dispositivo». `POST /demo/new-device`, sin cuerpo, invalida en el servidor el identificador de la cookie `web_session`, borra la cookie y devuelve 204. El cliente limpia `localStorage` y `sessionStorage` del origen y recarga la página para reiniciar su estado en memoria. Se conservan personas, trámites, eventos, mensajes del buzón y la conversación asociada al número de WhatsApp. Con `DEMO_MODE=false` ambas rutas están ausentes (404).
- `GET /health`.
- `POST /demo/reset` (borra y vuelve a cargar los datos semilla) y `POST /demo/seed`. Solo rol `admin` o `DEMO_MODE=true`.
- `GET /demo/mailbox?email=` (correos simulados con OTP). `POST /demo/cases/{id}/abandon` (fuerza el estado abandonado para la demo).

`GET /demo/mailbox?email=` solo está disponible con `DEMO_MODE=true`. Normaliza el correo y devuelve:

```json
{
  "messages": [
    {
      "id": "mail_...",
      "email": "ana.demo@example.com",
      "subject": "Tu código de verificación (demo)",
      "body": "Tu código de verificación es 123456.",
      "code": "123456",
      "created_at": "2026-11-24T16:00:00Z"
    }
  ]
}
```

`POST /demo/reset` elimina también todos los registros de `mailbox_messages` antes de recargar el seed.

El buzón público de demo revela si se envió un mensaje a un correo. Está disponible únicamente con `DEMO_MODE=true` y no existe en producción.

---

## 9. Motor conversacional (WhatsApp)

Reglas simples y deterministas (sin IA obligatoria). El estado se guarda en `channel_identities.session_state`; si el usuario se va y regresa, **se retoma donde se quedó**.

| Situación | Comportamiento |
|---|---|
| Nivel 0 | Saludo + opciones: *Cotizar estudio* / *Agendar cita*. Cotizar funciona sin datos (catálogo). |
| Agendar sin datos | Pide **solo lo que falta**, uno a uno: nombre completo, fecha de nacimiento (DD/MM/AAAA), correo, "¿para ti o para otra persona?" (si otra: parentesco, nombre y fecha de nacimiento del paciente). |
| Nivel 1 (teléfono reconocido) | "Hola {nombre}. Tienes un trámite pendiente. Para continuar necesito verificar que eres tú. ¿Cuál es tu fecha de nacimiento?" → si coincide, envía OTP al correo registrado (mostrar correo enmascarado) → espera el código. |
| Verificación fallida | Mensaje claro; 3 intentos máximo y bloqueo temporal. |
| Nivel 2 | Resume el trámite ("ultrasonido en Clínica X; falta: horario") y ofrece *Continuar / Empezar otro trámite / Hablar con un asesor*. Ofrece horarios como respuestas rápidas. |
| Ambigüedad (varias personas con el mismo teléfono) | Pide fecha de nacimiento para desambiguar; nunca muestra datos antes. |
| Texto no entendido | "No te entendí. Elige una opción:" + respuestas rápidas. |

Comprensión de texto: coincidencia por palabras clave (`hola`, `cotizar`, `agendar`, `continuar`, `asesor`, `cancelar`). Un resumen o interpretación con IA es **opcional** y debe estar detrás de la variable `AI_ENABLED` con respaldo por plantilla.

En eventos `mensaje_recibido`, el contenido de una fecha de nacimiento o de un OTP nunca se almacena: el payload contiene solamente `type = "dob_enviada"` o `type = "otp_enviado"`. Los mensajes salientes nunca incluyen el código OTP; solo indican el correo enmascarado y enlazan al buzón simulado desde la interfaz de demo.

---

## 10. Roles, permisos y enmascarado

| Recurso / acción | Paciente | Asesor | Admin |
|---|---|---|---|
| Ver su propio trámite y línea de tiempo simple | Sí (nivel 2) | — | — |
| Ver contexto completo de un paciente | No | Sí, **solo con verificación vigente** (queda auditado) | No (solo enmascarado) |
| Avanzar / confirmar trámite | Sí (el suyo, nivel 2) | Sí (paciente verificado) | No |
| Agregar notas internas | No | Sí | No |
| Tablero y métricas | No | No | Sí |
| Auditoría | No | No | Sí |
| Reset / seed de la demo | No | No | Sí |

**Enmascarado** (función única en `security.py`, usada por admin y por el SSE):
- Nombre: `A*** M.` · Teléfono: `***4821` · Correo: `a***@dominio.com` · Fecha de nacimiento: no se muestra.

Cada denegación por rol o falta de verificación → evento `acceso_denegado`.

---

## 11. Interfaces (frontend)

Una app React; **cada ruta es un cliente independiente que solo usa `src/api.js`** (no conoce `patient_id` ni la base de datos; usa el identificador propio de su canal).

| Ruta | Qué simula | Contenido |
|---|---|---|
| `/web` | Sitio web | Cotizador (estudio → precio demo) → agendar → formulario de preregistro (nombre, fecha de nacimiento, correo, teléfono, ¿para quién?) → clínica → horario → confirmar. La sesión del navegador es el identificador. Se puede cerrar a mitad. |
| `/whatsapp` | WhatsApp | Marco de teléfono con burbujas y respuestas rápidas. Campo para elegir el **número de teléfono simulado**. Envía interacciones y pinta las respuestas. Enlace al buzón. |
| `/callcenter` | Centro de contacto | Login de asesor. "Softphone": ingresar número y **simular llamada entrante** → búsqueda; botón de verificación asistida; panel con contexto, línea de tiempo y acciones (confirmar, agregar nota). Se actualiza en vivo. |
| `/app` | App móvil | Marco de teléfono. Login por correo + OTP. Muestra "Mis trámites", progreso y cita confirmada. Opcional: reagendar. |
| `/admin` | Tablero | Login de admin. KPIs, tabla de trámites enmascarada con el recorrido de canales, feed de eventos en vivo, bitácora de auditoría, botones de reset/seed. |
| `/mailbox` | Correo simulado | Bandeja pública de demo con los OTP enviados. |

Requisitos de UI: textos en español; estados de carga y error visibles; diseño sobrio y legible; funcionar en el celular (WhatsApp y App); el tablero debe mostrar claramente **por qué canales pasó cada trámite**.

---

## 12. Datos de demo (seed) y credenciales

Catálogo ficticio: 5 estudios (con instrucciones de preparación ficticias), 3 clínicas ("Clínica Puebla Centro (demo)", "Clínica Puebla Angelópolis (demo)", "Clínica Cholula (demo)"), horarios generados para los próximos 3 días entre 09:00 y 13:00 cada hora.

Personas semilla (todas ficticias, correos `@example.com`):
- **Ana Demo**: **no existe** al inicio (el demo la crea desde la web).
- **Luis Demo**: `luis.demo@example.com`, `+522221111111`, nacimiento `1985-04-12`; trámite en `clinica_elegida`, marcado como abandonado.
- **Marta Demo**: `marta.demo@example.com`, `+522229999999`, nacimiento `1982-08-20`.
- **Pablo Demo**: `pablo.demo@example.com`, `+522229999999`, nacimiento `2012-03-15`. Marta y Pablo comparten el teléfono para el caso de ambigüedad.
- Algunos trámites en estados variados para poblar el tablero.

Credenciales de prueba (documentar en README):
- Asesor: `asesor` / `Asesor#2026`
- Admin: `admin` / `Admin#2026`
- Paciente: correo ficticio + código OTP obtenido en `/mailbox` (no hay contraseña).

---

## 13. Seguridad y configuración

- `.env` (no se sube a git): `JWT_SECRET`, `CHANNEL_KEY_WEB`, `CHANNEL_KEY_WHATSAPP`, `CHANNEL_KEY_CALLCENTER`, `CHANNEL_KEY_APP`, `DATABASE_URL`, `ABANDON_MINUTES`, `DEMO_MODE`, `AI_ENABLED`. Proveer `.env.example`.
- Contraseñas con bcrypt; OTP solo como hash; JWT con expiración (8 h).
- CORS limitado al origen del frontend.
- Permisos verificados **en el backend** para cada endpoint (no solo ocultar botones).
- Nunca registrar datos personales completos en logs.
- Aviso de privacidad y consentimiento simulados en el primer contacto (evento `consentimiento_aceptado`).

---

## 14. Pruebas de aceptación (pytest)

Deben existir y pasar:
1. `test_ana_full_flow`: Web (preregistro + clínica) → WhatsApp (reconoce, dob, OTP, elige horario) → Callcenter (verificación asistida, confirma) → App (ve cita confirmada). Verifica estados, `canal_cambiado` y la línea de tiempo.
2. `test_interruption_resume`: abandonar a mitad de WhatsApp y regresar retoma el paso exacto.
3. `test_partial_info_prompts_missing`: con datos incompletos, el sistema pide **solo** lo que falta.
4. `test_unknown_number_no_data`: número desconocido → no se muestran datos.
5. `test_shared_phone_disambiguation`: dos personas con el mismo teléfono → pide fecha de nacimiento y no adivina.
6. `test_idempotency_duplicate_interaction`: misma `idempotency_key` no duplica eventos.
7. `test_version_conflict`: `expected_version` viejo → 409.
8. `test_otp_expiry_and_lockout`: OTP expirado y bloqueo tras 3 fallos.
9. `test_rbac_matrix`: cada rol solo accede a lo permitido (sección 10).
10. `test_admin_masking`: el admin nunca recibe datos sin enmascarar.
11. `test_agent_access_requires_verification_and_audits`: sin verificación → 403 + `acceso_denegado`; con verificación → `contexto_consultado`.

Escenarios de resiliencia de la demo: **interrupción**, **información parcial** e **identidad no reconocida**.

---

## 15. Orden de construcción (rebanadas)

Cada rebanada termina con pruebas verdes y el backend/frontend arrancando sin errores.

| Rebanada | Contenido | Definición de terminado |
|---|---|---|
| **S0 · Esqueleto** | Estructura de carpetas, FastAPI con `/health`, modelos y creación de tablas, seed básico, frontend con rutas vacías, `.env.example`, README inicial | `uvicorn` y `npm run dev` arrancan; `/health` responde; pytest corre |
| **S1 · Núcleo + Web** | persons, cases, events; endpoint de interacciones para `web` (preregistro, estudio, clínica, horario); estado derivado; timeline; idempotencia y versión | Se puede crear un trámite desde `/web` y ver su línea de tiempo en la API |
| **S2 · Identidad** | Niveles de confianza, reconocimiento, OTP, `dob_check`, buzón simulado, bloqueo, vigencia | Pruebas 4, 5, 8 verdes |
| **S3 · WhatsApp** | Adaptador, motor conversacional, simulador `/whatsapp` | Se retoma desde WhatsApp el trámite hecho en la web (prueba 2 y 3) |
| **S4 · Roles + Call Center** | Login, permisos, adaptador callcenter, consola del asesor, notas, auditoría | Pruebas 9 y 11 verdes; Ana se confirma desde `/callcenter` |
| **S5 · Admin + tiempo real** | Tablero, enmascarado, SSE, auditoría | Prueba 10 verde; el tablero se actualiza en vivo |
| **S6 · App + pulido** | `/app` (OTP), reagendar opcional, reset/seed, README con credenciales, `test_ana_full_flow` completo | Demo completa repetible con un clic de reset |

**Decisiones de recorte:** si al terminar S5 hay poco tiempo, la App (S6) se recorta; lo demás **no**.

---

## 16. Fuera de alcance (no construir)

Integraciones reales, pagos, catálogo/agenda reales, microservicios, colas de mensajes, IA como requisito, múltiples idiomas, registro/administración de usuarios por interfaz.
