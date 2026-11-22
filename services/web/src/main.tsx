import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";

// The DSH shell ships its own stylesheet; the legacy Flare theme is not loaded.
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
