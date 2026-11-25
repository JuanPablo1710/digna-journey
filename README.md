# Digna Journey

**Reto Salud Digna · Un paciente, una sola conversación.** Digna Journey conserva el mismo trámite al pasar de Web al chat simulado, App y Call Center. Cada canal retoma el avance que le corresponde y el tablero de administración muestra el recorrido y la auditoría enmascarada.

Todos los datos, estudios, clínicas, horarios y credenciales son ficticios. Consulta los [diagramas de arquitectura](docs/ARCHITECTURE.md).

## Instalación en Windows

Usa **Python 3.11 o posterior**, **Node.js 18.x o 20 o posterior** y **npm**. La instalación inicial descarga dependencias. Una vez instaladas, la demo local sirve también la fuente y el logo desde el propio frontend.

1. Abre PowerShell en la raíz del repositorio y crea la configuración local.

   ```powershell
   Copy-Item .env.example .env
   ```

   La configuración de ejemplo habilita `DEMO_MODE=true`, deja `VITE_API_URL` vacío para usar el proxy local y guarda SQLite en `backend/data/app.db`. Conserva el archivo `.env` en la raíz.

2. Instala el backend en un entorno virtual.

   ```powershell
   cd backend
   python -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   ```

3. En otra terminal, desde la raíz, instala el frontend.

   ```powershell
   cd frontend
   npm install
   ```

## Arranque

En la terminal de `backend`, ejecuta `python -m app.dev` con el Python del entorno virtual.

```powershell
$env:PYTHONIOENCODING = "utf-8"
.\.venv\Scripts\python.exe -m app.dev
```

La variable fija la salida de Python en UTF-8 también al redirigir los logs. Así el reset HTTP puede imprimir el inventario, que contiene flechas. El backend escucha en `127.0.0.1:8000`. Comprueba [el estado de la API](http://127.0.0.1:8000/health), consulta [Swagger](http://127.0.0.1:8000/docs) o abre [OpenAPI](http://127.0.0.1:8000/openapi.json). El arranque crea las tablas y completa los datos semilla que falten. En Windows, reinicia el backend después de editar código.

En la terminal de `frontend`, ejecuta:

```powershell
npm run dev
```

Vite usa el puerto **5173** por defecto y redirige las solicitudes de API al backend.

| Canal | URL | Uso |
|---|---|---|
| Web | [`/web`](http://localhost:5173/web) | Cotizar, preregistrar y retomar un borrador. |
| WhatsApp simulado | [`/whatsapp`](http://localhost:5173/whatsapp) | Reconocer por número, verificar y avanzar por chat. |
| App | [`/app`](http://localhost:5173/app) | Ver, iniciar, continuar y confirmar trámites. |
| Call Center | [`/callcenter`](http://localhost:5173/callcenter) | Simular una llamada y verificar como asesor. |
| Administración | [`/admin`](http://localhost:5173/admin) | Consultar recorridos, métricas y auditoría. |
| Buzón de demo | [`/mailbox`](http://localhost:5173/mailbox) | Consultar el último correo con el OTP. |
| Ingreso | [`/login`](http://localhost:5173/login) | Autenticar al personal. |

Si los puertos están ocupados, cierra las instancias anteriores o usa **8010** y **5174** para esta copia. Para usar esos puertos, abre `.env` en la raíz y configura:

```dotenv
FRONTEND_ORIGIN=http://localhost:5174
VITE_API_URL=http://localhost:8010
```

Desde `backend`, arranca la API en el puerto alternativo:

```powershell
$env:PYTHONIOENCODING = "utf-8"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8010 --timeout-graceful-shutdown 2
```

En `frontend`, ejecuta `npm run dev -- --port 5174 --strictPort`. Abre las mismas rutas en `http://localhost:5174` y las de la API en `http://localhost:8010`.

## Datos y credenciales de demostración

| Rol y persona | Correo o usuario | Contraseña | Teléfono | Fecha de nacimiento | Qué probar |
|---|---|---|---|---|---|
| Paciente · Ana Demo | `ana.demo@example.com` | Acceso por OTP | `+522220000001` | `1990-05-10` | Darla de alta en Web con **Ultrasonido abdominal** y completar el recorrido de cuatro canales. |
| Paciente · Marta Demo | `marta.demo@example.com` | Acceso por OTP | `+522229999999` | `1982-08-20` | Abrir el folio **C-1002**, que solicitó para Pablo. Probar también la desambiguación por teléfono compartido. |
| Asesor | `asesor` | `Asesor#2026` | — | — | Simular una llamada, verificar a la solicitante, consultar el contexto y confirmar. |
| Administrador | `admin` | `Admin#2026` | — | — | Revisar el recorrido enmascarado, los eventos en vivo y la bitácora. |

Ana se crea durante la demo. Su correo y teléfono quedan libres después de cada reset. Marta ya está en el seed y comparte teléfono con Pablo Demo, nacido el `2012-03-15`.

En App, escribe el correo y pulsa **Enviar código**. En el [buzón de demo](http://localhost:5173/mailbox), busca la misma dirección y usa el código del mensaje más reciente. En WhatsApp, el código se solicita después de validar la fecha de nacimiento del solicitante. Los códigos se generan en cada solicitud.

## Reproducir la demo y restablecer los datos

Sigue el [guion de 6:30 minutos](DEMO.md). El recorrido es **Web → WhatsApp → App → Call Center → Admin**. Usa el [inventario de datos](docs/DEMO_DATA.md) para los escenarios alternativos.

Con `DEMO_MODE=true` puedes elegir entre estas operaciones:

| Operación | Cómo ejecutarla | Resultado |
|---|---|---|
| Reset completo | **Reiniciar demo** en `/admin`, `POST /demo/reset` o `.\.venv\Scripts\python.exe -m app.modules.demo.reset` desde `backend`. | Reconstruye SQLite y recarga el seed. Borra el avance de la demo, vacía el buzón, invalida sesiones y actualiza el inventario. Vuelve a iniciar sesión después del reset. |
| Completar el seed | **Cargar datos faltantes** en `/admin`, o `POST /demo/seed` con `Authorization: Bearer <token de admin>`. | Inserta filas semilla faltantes sin reemplazar el avance. |

El reset HTTP comprueba el modo demo. El seed HTTP requiere además rol de administrador. El buzón simulado también requiere modo demo.

## Pruebas

Desde `backend`, ejecuta `python -m pytest` con el Python del entorno virtual.

```powershell
.\.venv\Scripts\python.exe -m pytest
```

La suite usa una base SQLite de pruebas. Cubre el recorrido de Ana, borradores y retoma, verificación y bloqueo, pertenencia y roles, conflictos de versión, idempotencia, auditoría, enmascarado, reset, seed y concurrencia con conexiones SSE abiertas. Para ejecutar solo el recorrido de Ana, agrega `tests/test_app.py -k ana_full_flow`. Desde `frontend`, puedes comprobar la compilación con `npm run build`.

## Repositorio

```text
backend/app/          FastAPI, catálogo, ORM, adaptadores y módulos de dominio
backend/tests/        Pruebas pytest
backend/data/         Bases locales SQLite
frontend/src/        Páginas React, tema visual y cliente de API
frontend/public/     Recursos estáticos de Digna Journey
docs/                Arquitectura, inventario y datos de apoyo
DEMO.md              Guion y escenas de respaldo
SPEC.md              Especificación y contratos
.env.example         Configuración local de ejemplo
```

## Límites del prototipo

- El chat, las llamadas, el correo y la agenda se simulan localmente. No hay integración con sistemas reales de Salud Digna, mensajería externa ni pagos.
- SQLite está pensado para una instancia local. La demo usa horarios ficticios de Ciudad de México y conserva las fechas de la API en UTC.
- El buzón público permite consultar códigos ficticios por correo en modo demo. Usa únicamente datos de demostración.
- El abandono de algunos trámites viene del seed. El marcado periódico y la reprogramación de citas desde App quedan pendientes.
