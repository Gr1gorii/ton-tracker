import React from "react";
import ReactDOM from "react-dom/client";
import "@fontsource-variable/manrope";
import { TonConnectUIProvider } from "@tonconnect/ui-react";
import App from "./App";
import "./index.css";
import "./gram-design.css";
import "./gram-workspace.css";

const tonConnectManifestUrl =
  (import.meta.env.VITE_TONCONNECT_MANIFEST_URL as string | undefined) ??
  new URL("/tonconnect-manifest.json", window.location.origin).toString();

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <TonConnectUIProvider
      manifestUrl={tonConnectManifestUrl}
      restoreConnection
      analytics={{ mode: "off" }}
      uiPreferences={{ theme: "SYSTEM", borderRadius: "m" }}
    >
      <App />
    </TonConnectUIProvider>
  </React.StrictMode>,
);
