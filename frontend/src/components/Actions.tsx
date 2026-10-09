import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Action, Advisor, Source, logContact } from "../api";

const WA_ICON =
  "M12 2a10 10 0 0 0-8.6 15.1L2 22l5-1.3A10 10 0 1 0 12 2Zm0 18.2a8.2 8.2 0 0 1-4.2-1.2l-.3-.2-3 .8.8-2.9-.2-.3A8.2 8.2 0 1 1 12 20.2Zm4.5-6.1c-.2-.1-1.5-.7-1.7-.8s-.4-.1-.6.1-.7.8-.8 1-.3.2-.5.1a6.7 6.7 0 0 1-3.3-2.9c-.3-.4.2-.4.6-1.3a.4.4 0 0 0 0-.4l-.8-1.9c-.2-.5-.4-.4-.6-.4h-.5a1 1 0 0 0-.7.3 3 3 0 0 0-.9 2.2 5.2 5.2 0 0 0 1.1 2.7 11.9 11.9 0 0 0 4.6 4c1.7.7 2.3.8 3.2.7a2.7 2.7 0 0 0 1.8-1.3 2.2 2.2 0 0 0 .1-1.3c0-.1-.2-.2-.4-.3Z";

const WhatsAppIcon = ({ size = 18 }: { size?: number }) => (
  <svg viewBox="0 0 24 24" width={size} height={size} aria-hidden>
    <path fill="currentColor" d={WA_ICON} />
  </svg>
);

/** Buttons that come with an answer. With several advisors, the button opens a picker. */
export function ActionButtons({ actions, conversationId }: { actions?: Action[]; conversationId?: string | null }) {
  const [picking, setPicking] = useState<Action | null>(null);
  if (!actions?.length) return null;
  return (
    <div className="actions">
      {actions.map((a) =>
        (a.advisors?.length ?? 0) > 1 ? (
          <button key={a.url} className="action action--whatsapp" onClick={() => setPicking(a)}>
            <WhatsAppIcon />
            {a.label}
          </button>
        ) : (
          <a
            key={a.url}
            className="action action--whatsapp"
            href={a.url}
            target="_blank"
            rel="noreferrer"
            onClick={() => logContact(conversationId, a.contact)}
          >
            <WhatsAppIcon />
            {a.label}
          </a>
        ),
      )}
      {picking && (
        <AdvisorPicker advisors={picking.advisors ?? []} conversationId={conversationId} onClose={() => setPicking(null)} />
      )}
    </div>
  );
}

function initials(name: string) {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase())
    .join("");
}

function Photo({ advisor }: { advisor: Advisor }) {
  const [broken, setBroken] = useState(false);
  if (!advisor.photo || broken) {
    return (
      <span className="advisor__photo advisor__photo--initials" aria-hidden>
        {initials(advisor.name)}
      </span>
    );
  }
  return <img className="advisor__photo" src={advisor.photo} alt="" loading="lazy" onError={() => setBroken(true)} />;
}

/** Pop-up with the sales advisors: photo, name, what they handle and "Contáctame". */
function AdvisorPicker({
  advisors,
  conversationId,
  onClose,
}: {
  advisors: Advisor[];
  conversationId?: string | null;
  onClose: () => void;
}) {
  const closeButton = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    closeButton.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return createPortal(
    <div className="picker" role="presentation" onClick={onClose}>
      <div
        className="picker__sheet"
        role="dialog"
        aria-modal="true"
        aria-labelledby="picker-title"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="picker__head">
          <div>
            <h2 id="picker-title">Elige tu asesor</h2>
            <p>Se abrirá WhatsApp con un mensaje que resume lo que hablaste con Osky.</p>
          </div>
          <button ref={closeButton} className="picker__close" onClick={onClose} aria-label="Cerrar">
            ✕
          </button>
        </header>
        <ul className="picker__list">
          {advisors.map((a) => (
            <li key={a.url} className="advisor">
              <Photo advisor={a} />
              <div className="advisor__info">
                <strong className="advisor__name">{a.name}</strong>
                {a.area && <span className="advisor__area">{a.area}</span>}
                {a.solutions.length > 0 && (
                  <span className="advisor__tags">
                    {a.solutions.slice(0, 3).map((s) => (
                      <span key={s} className="advisor__tag">
                        {s}
                      </span>
                    ))}
                  </span>
                )}
              </div>
              <a
                className="advisor__contact"
                href={a.url}
                target="_blank"
                rel="noreferrer"
                onClick={() => {
                  logContact(conversationId, a.name);
                  onClose();
                }}
              >
                <WhatsAppIcon size={16} />
                Contáctame
              </a>
            </li>
          ))}
        </ul>
      </div>
    </div>,
    document.body,
  );
}

/** "Fuente: ..." with a link when the source is a web page. */
export function SourceLabel({ source, className }: { source?: Source | null; className: string }) {
  if (!source) return null;
  if (!source.url) return <span className={className}>Fuente: {source.title} (dato oficial de CeluWeb)</span>;
  return (
    <a className={className} href={source.url} target="_blank" rel="noreferrer">
      Fuente: {source.title}
    </a>
  );
}
