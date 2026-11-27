import type { ReactNode } from 'react';
import { useEscape } from '../../hooks/useEscape';

interface ModalProps {
  label: string;
  title: string;
  description?: string;
  onClose: () => void;
  onSubmit: () => void;
  children: ReactNode;
  footer: ReactNode;
}

function Backdrop({ onClose, children }: { onClose: () => void; children: ReactNode }) {
  return (
    <div
      className="modal-backdrop"
      onClick={(event) => {
        if (event.target === event.currentTarget) {
          onClose();
        }
      }}
    >
      {children}
    </div>
  );
}

function ModalHead({ title, description }: { title: string; description?: string }) {
  return (
    <div className="modal-head">
      <h2>{title}</h2>
      {description && <p className="card-sub">{description}</p>}
    </div>
  );
}

/** Small centred dialog. Backdrop click, Escape and the footer buttons close it. */
export function Modal({
  label,
  title,
  description,
  onClose,
  onSubmit,
  children,
  footer,
}: ModalProps) {
  useEscape(onClose);
  return (
    <Backdrop onClose={onClose}>
      <form
        className="modal modal-form"
        role="dialog"
        aria-modal="true"
        aria-label={label}
        onSubmit={(event) => {
          event.preventDefault();
          onSubmit();
        }}
      >
        <ModalHead title={title} description={description} />
        <div className="modal-body">{children}</div>
        <div className="modal-foot">{footer}</div>
      </form>
    </Backdrop>
  );
}
