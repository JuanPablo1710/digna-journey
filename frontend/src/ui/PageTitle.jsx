import { useEffect } from "react";
import { useLocation } from "react-router-dom";

const channelTitles = {
  "/web": "Web",
  "/whatsapp": "WhatsApp",
  "/callcenter": "Call Center",
  "/app": "App",
  "/admin": "Administración",
  "/mailbox": "Buzón (demo)",
  "/login": "Ingreso",
};

export default function PageTitle() {
  const { pathname } = useLocation();

  useEffect(() => {
    const channel = channelTitles[pathname.toLowerCase().replace(/\/+$/, "")];
    document.title = channel ? `${channel} · Digna Journey` : "Digna Journey";
  }, [pathname]);

  return null;
}
