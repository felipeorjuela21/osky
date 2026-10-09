import { Action, Source } from "../api";

const WA_ICON =
  "M12 2a10 10 0 0 0-8.6 15.1L2 22l5-1.3A10 10 0 1 0 12 2Zm0 18.2a8.2 8.2 0 0 1-4.2-1.2l-.3-.2-3 .8.8-2.9-.2-.3A8.2 8.2 0 1 1 12 20.2Zm4.5-6.1c-.2-.1-1.5-.7-1.7-.8s-.4-.1-.6.1-.7.8-.8 1-.3.2-.5.1a6.7 6.7 0 0 1-3.3-2.9c-.3-.4.2-.4.6-1.3a.4.4 0 0 0 0-.4l-.8-1.9c-.2-.5-.4-.4-.6-.4h-.5a1 1 0 0 0-.7.3 3 3 0 0 0-.9 2.2 5.2 5.2 0 0 0 1.1 2.7 11.9 11.9 0 0 0 4.6 4c1.7.7 2.3.8 3.2.7a2.7 2.7 0 0 0 1.8-1.3 2.2 2.2 0 0 0 .1-1.3c0-.1-.2-.2-.4-.3Z";

/** Buttons that come with an answer (e.g. "Hablar con un asesor por WhatsApp"). */
export function ActionButtons({ actions }: { actions?: Action[] }) {
  if (!actions?.length) return null;
  return (
    <div className="actions">
      {actions.map((a) => (
        <a key={a.url} className="action action--whatsapp" href={a.url} target="_blank" rel="noreferrer">
          <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden>
            <path fill="currentColor" d={WA_ICON} />
          </svg>
          {a.label}
        </a>
      ))}
    </div>
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
