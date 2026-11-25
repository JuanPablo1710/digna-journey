# Motor de contexto omnicanal

Prototipo ficticio para Salud Digna. Un trámite conserva sus datos, avance y eventos al pasar de Web a WhatsApp, Call Center y App. El tablero de administración muestra métricas y auditoría enmascarada.

## Arquitectura

El frontend React y Vite usa `src/api.js` para hablar con FastAPI. Los adaptadores de canal traducen interacciones y el núcleo aplica verificación, permisos, estado derivado y versiones. SQLite guarda trámites y eventos en transacciones. El tablero y Call Center reciben eventos confirmados por SSE. Consulta los diagramas y las diferencias con la especificación en [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Instalación local

Necesitas Python 3.11 o posterior y Node.js 18 o posterior.

1. Desde la raíz, copia `.env.example` a `.env`. Los valores de ejemplo son para una demo local.

   ```powershell
   Copy-Item .env.example .env
   ```

2. Desde la raíz, abre una terminal para el backend.

   ```powershell
   cd backend
   python -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   .\.venv\Scripts\python.exe -m app.dev
   ```

   En Windows, reinicia el backend manualmente tras editar código. El supervisor de recarga de Uvicorn puede quedarse esperando al proceso anterior. El arranque conserva la recarga automática en otros sistemas y limita a dos segundos la espera por conexiones abiertas al apagar el servidor. El comando equivalente en Windows es `python -m uvicorn app.main:app --timeout-graceful-shutdown 2`.

3. En otra terminal, desde la raíz, instala y arranca el frontend.

   ```powershell
   cd frontend
   npm ci
   npm run dev
   ```

Abre `http://localhost:5173/web`. Los contratos de la API se publican en `http://localhost:8000/docs` y `http://localhost:8000/openapi.json`. Las pruebas de red y cookies de desarrollo usan el proxy de Vite.

## Pruebas y compilación

Desde `backend`, ejecuta `python -m pytest` con el mismo entorno virtual del backend. Para aislar el recorrido de cuatro canales usa `python -m pytest tests/test_app.py -k ana_full_flow`. Desde `frontend`, ejecuta `npm run build`.

## Reset de la demo

Con `DEMO_MODE=true`, ejecuta `python -m app.modules.demo.reset` desde `backend` o pulsa **Reiniciar demo** en `/admin`. Esto reemplaza todos los datos locales de demo, invalida sesiones y genera el inventario [DEMO_DATA.md](docs/DEMO_DATA.md). El botón **Cargar datos faltantes** completa el seed sin borrar datos.

## Accesos de prueba

| Rol | Cómo entrar |
|---|---|
| Asesor | `/login` con `asesor` / `Asesor#2026` |
| Admin | `/login` con `admin` / `Admin#2026` |
| Paciente | En `/app`, solicita un OTP con `marta.demo@example.com` o el correo de Ana. Consulta el código en `/mailbox`. |

Para replicar el recorrido Web → WhatsApp → App → Call Center → Admin, sigue [DEMO.md](DEMO.md). Ana comienza sin datos. Marta y Pablo comparten un número en el seed. Con el OTP de Marta puedes continuar su trámite para Pablo o iniciar otro con los mismos datos de paciente.

En `/app`, abre un folio en **Mis trámites** para ver su línea de tiempo y completar los pasos pendientes. También puedes pulsar **Iniciar un trámite** y agendar para ti u otra persona. La App reutiliza la sesión verificada vigente y la renueva hasta 30 minutos desde la última actividad autenticada, dentro de la vigencia del JWT. Las acciones y sus formatos están en [SPEC.md, sección 8.3.3](SPEC.md#833-formatos-de-app).

## Límites de la demo

- Todos los datos son ficticios. El buzón es público solo en modo demo y revelar el correo permite consultar sus mensajes. WhatsApp y las llamadas son simulaciones.
- App permite iniciar, continuar y confirmar trámites. Reagendar una cita confirmada queda pendiente como función opcional.
- Los horarios de clínicas son ficticios, de 09:00 a 13:00 en Ciudad de México. Las marcas de tiempo se guardan en UTC.
- SQLite está pensado para una instancia de la demo. El plazo de abandono se conserva como configuración, pero el marcado periódico no está implementado.
- El despliegue en un solo origen requiere habilitar el servicio de archivos estáticos descrito en [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md). Es una propuesta pendiente de aprobación.
