import React, { lazy, Suspense } from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import "./index.css";

const Admin = lazy(() => import("./pages/Admin"));
const AppPage = lazy(() => import("./pages/App"));
const CallCenter = lazy(() => import("./pages/CallCenter"));
const Login = lazy(() => import("./pages/Login"));
const Mailbox = lazy(() => import("./pages/Mailbox"));
const Web = lazy(() => import("./pages/Web"));
const WhatsApp = lazy(() => import("./pages/WhatsApp"));

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <BrowserRouter>
      <Suspense fallback={<p className="p-5" role="status">Cargando…</p>}>
        <Routes>
          <Route path="/web" element={<Web />} />
          <Route path="/whatsapp" element={<WhatsApp />} />
          <Route path="/callcenter" element={<CallCenter />} />
          <Route path="/app" element={<AppPage />} />
          <Route path="/admin" element={<Admin />} />
          <Route path="/mailbox" element={<Mailbox />} />
          <Route path="/login" element={<Login />} />
          <Route path="*" element={<Navigate to="/web" replace />} />
        </Routes>
      </Suspense>
    </BrowserRouter>
  </React.StrictMode>,
);

