# AGENTS.md

Proyecto: motor de contexto omnicanal para Salud Digna (HackaTec 2026).

## Reglas de trabajo

- Antes de cualquier tarea, lee `SPEC.md`. Es la fuente de verdad. Si algo no está ahí, pregunta en vez de inventar.
- Construye **una rebanada a la vez** (sección 15 del SPEC). No empieces la siguiente hasta que se te pida.
- No cambies endpoints, tablas, eventos ni reglas sin avisar. Si hace falta un cambio, propónlo y actualiza `SPEC.md` solo cuando se apruebe.
- Los canales (frontend) solo hablan con la API a través de `frontend/src/api.js`. Nunca acceden a la base de datos ni conocen el `patient_id`.
- La tabla `events` es inmutable: nunca UPDATE ni DELETE.
- Todos los datos son ficticios. No integres servicios externos reales.
- Textos de interfaz y mensajes al usuario en español; código, tablas y endpoints en inglés.
- No subas secretos: `.env` va en `.gitignore`; mantén `.env.example` actualizado.

## Comandos

- Backend: `cd backend && pip install -r requirements.txt && python -m app.dev`
- Pruebas: `cd backend && pytest`
- Frontend: `cd frontend && npm install && npm run dev`

## Al terminar cada tarea

1. Corre las pruebas y confirma que pasan.
2. Resume en pocas líneas qué cambió, qué archivos tocaste y qué quedó pendiente.
3. Indica cómo probarlo a mano (comando o URL).
