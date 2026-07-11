import React from "react";
import ReactDOM from "react-dom/client";
import "@fontsource-variable/manrope";
import App from "./App";
import "./index.css";
import "./gram-design.css";
import "./gram-workspace.css";

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
