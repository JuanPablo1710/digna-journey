# Propuesta de despliegue en una URL

FastAPI serviría la API y el frontend compilado bajo el mismo dominio HTTPS. El empaquetado queda pendiente de aprobación.

## Decisiones y efectos

| Decisión | Ventaja | Costo |
|---|---|---|
| FastAPI sirve Vite compilado | Las llamadas usan rutas relativas. API, cookies y SSE comparten origen. | Una publicación actualiza ambas capas. |
| SQLite en volumen | Conserva trámites, usuarios y eventos después de redeplegar. | El proveedor debe ofrecer disco persistente. Mantener una sola instancia simplifica las escrituras. |
| SQLite efímero | Permite una demo reproducible incluso sin volumen. | Reiniciar la instancia o redeplegar puede perder el avance. El arranque vuelve a cargar el seed inicial. |

Para una exposición corta, la opción efímera es suficiente si se admite preparar la demo de nuevo. Para ensayos repetidos con datos que se quieran conservar, usa un volumen.

## Pasos propuestos

1. Compilar Vite con `npm ci` y `npm run build`, dejando `VITE_API_URL` vacío. El frontend conserva las rutas relativas.
2. Registrar primero los routers de FastAPI. Servir `frontend/dist/assets` en `/assets` y devolver `frontend/dist/index.html` solo para las rutas React conocidas. Así, una ruta de API inexistente conserva su 404. Excluir el tráfico SSE de compresión con búfer o caché del proxy.
3. Empaquetar una imagen de dos etapas. La primera usa Node y genera `frontend/dist`. La segunda instala `backend/requirements.txt`, copia `backend/app` y ese `dist`, y arranca `uvicorn app.main:app --host 0.0.0.0 --port 8000` desde `backend`. La imagen lleva código y recursos compilados, con los secretos inyectados al arrancar.
4. En un servicio de contenedores con nivel gratuito, publicar el puerto configurado y comprobar que el plan admite conexiones SSE y el modo de disco elegido. Si el servicio suspende la instancia por inactividad, permite un arranque en frío antes de la presentación. Usa HTTPS en el dominio asignado.
5. Configurar `DATABASE_URL=sqlite:////data/app.db` y una carpeta escribible `/data`. Conecta ese punto a un volumen para conservar datos. El arranque crea tablas y completa el seed que falte. Ejecutar el reset manualmente solo cuando se quiera reemplazar la demo.

## Variables

| Momento | Variables |
|---|---|
| Build de Vite | `VITE_API_URL` vacío y las cuatro `VITE_CHANNEL_KEY_*` iguales a las claves del servidor. Las claves en el bundle son visibles y solo simulan el canal. |
| Arranque de FastAPI | `JWT_SECRET` aleatorio fuera del repositorio; `CHANNEL_KEY_WEB`, `CHANNEL_KEY_WHATSAPP`, `CHANNEL_KEY_CALLCENTER`, `CHANNEL_KEY_APP`; `DATABASE_URL`; `FRONTEND_ORIGIN` con el origen HTTPS; `DEMO_MODE`, `LOCKOUT_MINUTES`, `ABANDON_MINUTES` y `AI_ENABLED`. |

Con `DEMO_MODE=true`, las operaciones de demo y el buzón público exponen funciones para presentar datos ficticios. La configuración se usa únicamente en una instancia de demo.
