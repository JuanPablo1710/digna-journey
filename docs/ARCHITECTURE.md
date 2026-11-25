# Arquitectura

## Componentes

```mermaid
flowchart LR
    subgraph React["React y Vite"]
        W["Web"]
        WA["WhatsApp simulado"]
        CC["Call Center simulado"]
        A["App"]
        ADM["Admin"]
        API["src/api.js"]
        W --> API
        WA --> API
        CC --> API
        A --> API
        ADM --> API
    end
    subgraph FastAPI
        Adapt["Adaptadores de canal"]
        Access["Identidad, roles y OTP"]
        Cases["Trámites, pasos y versión"]
        Events["Eventos inmutables"]
        Read["Administración y SSE enmascarados"]
        Demo["Seed, reset y buzón de demo"]
        Adapt --> Access
        Adapt --> Cases
        Cases --> Events
        Access --> Events
    end
    DB[("SQLite mediante SQLAlchemy")]
    API --> Adapt
    API --> Access
    API --> Read
    API --> Demo
    Access --> DB
    Cases --> DB
    Events --> DB
    Demo --> DB
    DB -->|"Solo eventos confirmados"| Read
    Read -->|"SSE con Bearer"| API
```

## Recorrido de Ana

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
    Ana->>Web: Elige estudio y registra sus datos
    Web->>API: Preregistro
    API->>DB: Guarda el trámite y los eventos
    API-->>Web: Folio y estado datos completos
    Ana->>WA: Retoma con su teléfono
    WA->>API: Reconocimiento y fecha de nacimiento
    API->>OTP: Deposita código simulado
    Ana->>WA: Valida el código y elige clínica
    WA->>API: Selección de clínica con versión
    API->>DB: Conserva el folio y registra cambio de canal y clínica
    opt Sesión App nueva o vencida
        Ana->>App: Ingresa su correo
        App->>API: Solicita código OTP
        API->>OTP: Deposita un código para App
        Ana->>App: Ingresa el último código
        App->>API: Confirma código
    end
    App->>API: Consulta y abre el trámite con versión
    Ana->>App: Elige horario de Ciudad de México
    App->>API: Selección de horario con versión
    API->>DB: Registra el cambio a App y guarda el horario
    Ana->>CC: Llama para confirmar
    CC->>API: Verifica fecha de nacimiento del solicitante
    API-->>CC: Contexto y horario ya capturados
    CC->>API: Confirma la cita con versión
    API->>DB: Registra cambio a Call Center y cita confirmada
    Admin->>API: Consulta el tablero
    API-->>Admin: Estado y recorrido enmascarados
```

## Modelo de datos

```mermaid
erDiagram
    PERSON o|--o{ CHANNEL_IDENTITY : vincula
    PERSON ||--o{ VERIFICATION : acredita
    PERSON ||--o{ CASE : solicita
    PERSON ||--o{ CASE : recibe
    PERSON o|--o{ USER : representa
    CHANNEL_IDENTITY ||--o| DRAFT : conserva
    PERSON o|--o{ DRAFT : inicia
    CASE o|--o{ EVENT : registra
    PERSON o|--o{ EVENT : sujeto
    CASE ||--o{ NOTE : contiene
    USER ||--o{ NOTE : escribe
    PERSON {
        string id PK
        string email
        string phone
        date birth_date
    }
    CHANNEL_IDENTITY {
        string id PK
        string person_id FK
        string channel
        string identifier
        json session_state
    }
    VERIFICATION {
        string id PK
        string person_id FK
        string method
        string status
        datetime valid_until
    }
    CASE {
        string id PK
        string requester_id FK
        string patient_id FK
        string relationship
        json steps
        string status
        int version
    }
    EVENT {
        int seq PK
        string event_id UK
        string case_id FK
        string person_id FK
        string type
        json payload
    }
    USER {
        string id PK
        string person_id FK
        string role
    }
    NOTE {
        string id PK
        string case_id FK
        string author_user_id FK
    }
    DRAFT {
        string id PK
        string identity_id FK
        string requester_id FK
        json data
    }
    RESUME_CHALLENGE {
        string id PK
        string code_hash
        json scope
        datetime valid_until
    }
    MAILBOX_MESSAGE {
        string id PK
        string email
        string code
        datetime created_at
    }
```

`RESUME_CHALLENGE.scope` representa el alcance temporal de la retoma. El buzón es una simulación de entrega por correo y carece de una relación por clave externa.

## Diferencias conocidas con SPEC.md

| Tema | Implementación |
|---|---|
| Reagendar desde App | Función opcional pendiente. La App inicia, retoma y confirma trámites. |
| Folio corto de retoma y búsqueda por teléfono con fecha | La retoma usa correo con OTP. App muestra el identificador de trámite existente como folio. |
| Abandono | Hay ejemplos en el seed y recuperación al retomar. La tarea periódica y `POST /demo/cases/{id}/abandon` siguen pendientes. |
| Verificación asistida | El asesor valida la fecha de nacimiento. El dictado de OTP al asesor sigue pendiente. |
| Borradores | La persistencia indexada usa `drafts` y los adaptadores conservan el estado de canal en `channel_identities.session_state`. |
| Reset HTTP | Conserva el modo demo y el comando existente. El seed complementario exige admin y modo demo. |
| Canales reales | Correo, WhatsApp y llamadas se simulan. El buzón demo público muestra los códigos por correo. |
| Un solo origen | La configuración local usa proxy de Vite. El empaquetado en FastAPI está en [propuesta](DEPLOYMENT.md). |
