import React from "react";
import ReactDOM from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router-dom";

import { App } from "./App";
import { AuthProvider } from "./lib/auth";
import { ToastProvider } from "./components/ui";
import "./styles/global.css";
import "./styles/platform.css";
import "./styles/report-desk.css";

const router = createBrowserRouter([{ path: "*", element: (
      <ToastProvider>
        <AuthProvider>
          <App />
        </AuthProvider>
      </ToastProvider>
)}]);

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <RouterProvider router={router} />
  </React.StrictMode>,
);
