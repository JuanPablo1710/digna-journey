import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import "./index.css";
import Admin from "./pages/Admin";
import AppPage from "./pages/App";
import CallCenter from "./pages/CallCenter";
import Login from "./pages/Login";
import Mailbox from "./pages/Mailbox";
import Web from "./pages/Web";
import WhatsApp from "./pages/WhatsApp";

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <BrowserRouter>
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
    </BrowserRouter>
  </React.StrictMode>,
);

