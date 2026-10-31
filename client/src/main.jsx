import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { AuthProvider } from "./core/auth/AuthContext";
import "./index.css";
import { applyTheme } from "./core/ui/theme";
import { preventPinchZoom } from "./core/ui/pinchZoom";
import { centerNewForms } from "./core/ui/centerForms";
applyTheme();
preventPinchZoom();
centerNewForms();
ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <App />
      </AuthProvider>
    </BrowserRouter>
  </React.StrictMode>,
);
