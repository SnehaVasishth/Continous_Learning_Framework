import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import App from "./App";
import { OperatorProvider } from "./lib/operator";
import "./index.css";

// Mirror the SalesOps app's base-path convention so the production URL
// (https://app.solution.zbrain.ai/keysight-salesops-governance/) and the
// dev URL line up. Trailing slash trimmed for React Router's basename.
const BASENAME = (import.meta.env.BASE_URL || "/").replace(/\/$/, "");

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter basename={BASENAME || undefined}>
      <OperatorProvider>
        <App />
      </OperatorProvider>
    </BrowserRouter>
  </StrictMode>,
);
