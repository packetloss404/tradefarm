import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./index.css";
import { DEFAULT_SETTINGS } from "./settings";
import { setBackendBase } from "./shared/api";

// Initialize the REST base URL synchronously BEFORE React mounts so SWR's
// initial fetch (which fires on first render) doesn't go to the Tauri
// custom-protocol host and return index.html. The async loadSettings() call
// inside <App/> may overwrite this with a persisted user value, but by then
// any inflight initial requests will have already targeted the correct host.
setBackendBase(DEFAULT_SETTINGS.backendBaseUrl);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
