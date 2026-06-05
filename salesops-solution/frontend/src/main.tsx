import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import App from "./App";
import { bootstrapTheme } from "./hooks/useTheme";
import { OperatorProvider } from "./lib/operator";
import "./index.css";

bootstrapTheme();

// Same base used by vite.config.ts so client-side routing stays in step with
// asset URLs. Trailing slash trimmed for React Router's basename contract.
const BASENAME = (import.meta.env.BASE_URL || "/").replace(/\/$/, "");

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter basename={BASENAME || undefined}>
      <OperatorProvider>
        <App />
      </OperatorProvider>
    </BrowserRouter>
  </StrictMode>
);
