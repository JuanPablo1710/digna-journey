# Arquitectura de Digna Journey

## Arquitectura de la solución

React usa `frontend/src/api.js` como único cliente HTTP. Con la configuración local por defecto, Vite reenvía las solicitudes de API a FastAPI. Los adaptadores reciben interacciones con la clave del canal y las convierten en operaciones del dominio. El motor conversacional determina el siguiente paso en el chat simulado.

```mermaid
flowchart LR
    subgraph React["React y Vite"]
        W["Web"]
        WA["WhatsApp simulado"]
        CC["Call Center simulado"]
        A["App"]
        ADM["Admin"]
        LOGIN["Ingreso de personal"]
        MB["Buzón de demo"]
        API["src/api.js"]
        W --> API
        WA --> API
        CC --> API
        A --> API
        ADM --> API
        LOGIN --> API
        MB --> API
    end
    subgraph Backend["FastAPI"]
        Adapt["Adaptadores Web, WhatsApp, App y Call Center"]
        Chat["Motor conversacional"]
        Staff["Consola del asesor"]
        Board["Tablero y auditoría enmascarados"]
        Stream["Tiempo real · GET /stream"]
        Demo["Reset, seed y buzón de demo"]
        subgraph Core["Núcleo"]
            Access["Identidad, OTP y retoma"]
            Roles["Autorización · paciente, asesor, admin"]
            Cases["Trámites, pasos, versión e idempotencia"]
            Events["Registro de eventos inmutables"]
        end
        Adapt --> Access & Cases & Chat
        Chat --> Access & Cases
        Staff --> Roles & Access & Cases & Events
        Board --> Roles
        Stream --> Roles
        Cases --> Events
        Access --> Events
    end
    DB[("SQLite mediante SQLAlchemy")]
    API --> Adapt & Access & Roles & Staff & Board & Demo & Stream
    Access & Roles & Cases & Events & Demo --> DB
    DB --> Board
    DB -->|"Eventos después del commit"| Stream
    Stream -->|"SSE con Bearer y alcance por rol"| API
```

Los cambios del trámite y sus eventos se guardan en la misma transacción. SSE lee eventos ya confirmados, enmascara la salida y permite reanudar con `Last-Event-ID`. El administrador ve el feed enmascarado. El asesor recibe actualizaciones correspondientes a su alcance verificado. Los pacientes usan su sesión de canal y los endpoints de trámites.

## Recorrido de Ana entre canales

```mermaid
sequenceDiagram
    actor Ana
    participant Web
    participant WA as WhatsApp
    participant App
    participant CC as Call Center
    participant Admin
    participant API as FastAPI
    participant OTP as Buzón de demo
    participant DB as SQLite
    Ana->>Web: Cotiza Ultrasonido abdominal y captura sus datos
    Web->>API: Guarda el borrador
    Ana->>Web: Recarga en la misma sesión
    Web->>API: Recupera el borrador
    Ana->>Web: Guarda y continúa
    Web->>API: Envía el preregistro
    API->>DB: Guarda el trámite y los eventos
    API-->>Web: Folio y estado datos completos
    Ana->>WA: Retoma con su teléfono
    WA->>API: Reconocimiento y fecha de nacimiento
    API->>OTP: Deposita código simulado
    Ana->>OTP: Consulta el último código de WhatsApp
    Ana->>WA: Envía el código y elige clínica
    WA->>API: Selección de clínica con versión
    API->>DB: Conserva el folio y registra cambio de canal y clínica
    opt Sesión App nueva o vencida
        Ana->>App: Ingresa su correo
        App->>API: Solicita código OTP
        API->>OTP: Deposita un código para App
        Ana->>OTP: Consulta el nuevo código de App
        Ana->>App: Ingresa el código
        App->>API: Confirma código
    end
    App->>API: GET /me/cases y apertura del folio con versión
    Ana->>App: Elige horario de Ciudad de México
    App->>API: Selección de horario con versión
    API->>DB: Registra el cambio a App y guarda el horario
    Ana->>CC: Llama para confirmar
    CC->>API: Registra llamada y busca por teléfono
    API-->>CC: Ana reconocida con nombre enmascarado
    CC->>API: Verifica fecha de nacimiento de la solicitante
    API-->>CC: Contexto y horario ya capturados
    CC->>API: Confirma la cita con versión
    API->>DB: Registra cambio a Call Center y cita confirmada
    opt Admin ya conectado al stream
        API-->>Admin: Evento cita_confirmada por SSE
    end
    Admin->>API: Consulta el tablero
    API-->>Admin: Estado y recorrido enmascarados
```

## Modelo de datos

Los nombres de entidades corresponden a las diez tablas de `backend/app/models.py`. Las relaciones indican las claves externas del ORM.

```mermaid
erDiagram
    persons o|--o{ channel_identities : vincula
    persons ||--o{ verifications : acredita
    persons ||--o{ cases : solicita
    persons ||--o{ cases : recibe
    persons o|--o{ users : representa
    channel_identities ||--o| drafts : conserva
    persons o|--o{ drafts : inicia
    cases o|--o{ events : registra
    persons o|--o{ events : sujeto
    cases ||--o{ notes : contiene
    users ||--o{ notes : escribe
    persons {
        string id PK
        string full_name
        string email
        string phone
        date birth_date
        boolean is_provisional
        datetime created_at
    }
    channel_identities {
        string id PK
        string person_id FK
        string channel
        string identifier
        string identifier_type
        json session_state
        datetime last_seen_at
    }
    verifications {
        string id PK
        string person_id FK
        string channel
        string identifier
        string method
        string code_hash
        string status
        int attempts
        datetime expires_at
        datetime valid_until
        datetime created_at
    }
    cases {
        string id PK
        string requester_id FK
        string patient_id FK
        string relationship
        string study_id
        string clinic_id
        string slot_id
        datetime slot_datetime
        json steps
        string status
        boolean abandoned
        string current_channel
        string last_channel
        int version
        datetime created_at
        datetime updated_at
    }
    events {
        int seq PK
        string event_id UK
        string case_id FK
        string person_id FK
        string type
        string channel
        string actor_role
        string actor_id
        datetime timestamp
        json payload
        string idempotency_key UK
    }
    users {
        string id PK
        string username UK
        string password_hash
        string person_id FK
        string role
    }
    notes {
        string id PK
        string case_id FK
        string author_user_id FK
        text text
        datetime created_at
    }
    drafts {
        string id PK
        string identity_id FK, UK
        string requester_id FK
        string email
        json data
        int version
        datetime updated_at
        datetime expires_at
    }
    resume_challenges {
        string id PK
        string email
        string channel
        string destination
        string code_hash
        int attempts
        datetime expires_at
        datetime locked_until
        json scope
        json selections
        datetime valid_until
    }
    mailbox_messages {
        string id PK
        string email
        string subject
        text body
        string code
        datetime created_at
    }
```

`channel_identities` tiene una restricción única sobre `(channel, identifier)`. `resume_challenges.scope` y `selections` guardan el alcance y las selecciones de retoma en JSON. El buzón y los desafíos de retoma se buscan por correo. Los identificadores de estudio, clínica y horario se refieren al catálogo definido en código. El identificador de llamada se conserva en los eventos correspondientes.

## Diferencias conocidas con SPEC.md

| Tema | Implementación |
|---|---|
| Reagendar desde App | Función opcional pendiente. La App inicia, retoma y confirma trámites. |
| Folio corto de retoma y búsqueda por teléfono con fecha | La retoma usa correo con OTP. App muestra el identificador de trámite existente como folio. |
| Abandono | Hay ejemplos en el seed y recuperación al retomar. La tarea periódica y `POST /demo/cases/{id}/abandon` siguen pendientes. |
| Verificación asistida | El asesor valida la fecha de nacimiento. El dictado de OTP al asesor sigue pendiente. |
| Borradores | La persistencia indexada usa `drafts` y los adaptadores conservan el estado de canal en `channel_identities.session_state`. |
| Reset HTTP y seed | `POST /demo/reset` comprueba `DEMO_MODE` y está disponible sin token en modo demo. `POST /demo/seed` exige también rol de administrador. |
| Canales reales | Correo, WhatsApp y llamadas se simulan. El buzón demo público muestra los códigos por correo. |
| Un solo origen | La configuración local usa proxy de Vite. El empaquetado en FastAPI está en [propuesta](DEPLOYMENT.md). |
