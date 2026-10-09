import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { unlockAudio } from "./audio";
import "./styles.css";

// Browsers (iPhone above all) only allow sound after a tap: unlock it on the first one.
const unlockOnce = () => {
  unlockAudio();
  window.removeEventListener("pointerdown", unlockOnce);
  window.removeEventListener("keydown", unlockOnce);
};
window.addEventListener("pointerdown", unlockOnce);
window.addEventListener("keydown", unlockOnce);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
