import "./rig.css";

export type RigState = "idle" | "listening" | "thinking" | "speaking";
export type RigMood = "neutral" | "happy" | "curious" | "unsure";
export type RigGesture = "" | "wave" | "nod" | "shrug";

const PART = (name: string) => `/oski-rig/${name}.png`;

/* The astronaut cut into layers (frontend/scripts/build_rig.py) and animated
   from its joints. Reads --talk, --mic, --look-x and --look-y from an ancestor. */
export function OskiRig({
  state,
  mood = "neutral",
  gesture = "",
}: {
  state: RigState;
  mood?: RigMood;
  gesture?: RigGesture;
}) {
  const classes = ["rig", `rig--${state}`, `rig--mood-${mood}`, gesture && `rig--g-${gesture}`];
  return (
    <div className={classes.filter(Boolean).join(" ")} aria-hidden>
      <span className="rig__puffs">
        <i />
        <i />
        <i />
      </span>
      <img className="rig__part rig__leg-back" src={PART("leg-back")} alt="" draggable={false} />
      <img className="rig__part rig__leg-front" src={PART("leg-front")} alt="" draggable={false} />
      <img className="rig__part rig__body" src={PART("body")} alt="" draggable={false} />
      <img className="rig__part rig__arm-right" src={PART("arm-right")} alt="" draggable={false} />
      <div className="rig__part rig__arm-left">
        <img className="rig__part" src={PART("arm-left")} alt="" draggable={false} />
        <img className="rig__part rig__hand" src={PART("hand-left")} alt="" draggable={false} />
      </div>
      <div className="rig__part rig__helmet">
        <img className="rig__part" src={PART("helmet")} alt="" draggable={false} />
        {/* light inside the gold visor: warm with Osky's voice, green with yours */}
        <span className="rig__visor-glow" />
      </div>
    </div>
  );
}
