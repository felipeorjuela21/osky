import { CSSProperties } from "react";
import { OskiRig } from "./OskiRig";

export type AgentState = "idle" | "listening" | "thinking" | "speaking";

const LABELS: Record<AgentState, string> = {
  idle: "Listo para ayudarte",
  listening: "Escuchando…",
  thinking: "Buscando en la información de CeluWeb…",
  speaking: "Hablando",
};

/* Compact articulated Osky for chat mode. */
export function OskiAvatar({ state, mouthOpen }: { state: AgentState; mouthOpen: boolean }) {
  const talk = { "--talk": state === "speaking" && mouthOpen ? 0.8 : 0 } as CSSProperties;

  return (
    <div className={`avatar avatar--${state}`} aria-live="polite">
      <div className="avatar__stage" style={talk}>
        <span className="avatar__ring" />
        <span className="avatar__ring avatar__ring--2" />
        <div className="avatar__rig">
          <OskiRig state={state} />
        </div>
      </div>
      <p className="avatar__label">{LABELS[state]}</p>
    </div>
  );
}
