import { useEffect, useRef, useState } from "react";
import {
  SpinnerGap,
  Trash,
  WarningCircle,
  X,
} from "@phosphor-icons/react";

import type { WalletCaseDeletionResponse } from "../walletCase";
import { deleteWalletCase } from "../walletCaseApi";

const CONFIRMATION = "DELETE";

export default function CaseDeleteDialog({
  caseId,
  caseName,
  open,
  onClose,
  onDeleted,
}: {
  caseId: string;
  caseName: string;
  open: boolean;
  onClose: () => void;
  onDeleted: (receipt: WalletCaseDeletionResponse) => void;
}) {
  const [confirmation, setConfirmation] = useState("");
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const controllerRef = useRef<AbortController | null>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    if (!open) return;
    setConfirmation("");
    setDeleting(false);
    setError(null);
    inputRef.current?.focus();
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape" && !controllerRef.current) onCloseRef.current();
    }
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      controllerRef.current?.abort();
      controllerRef.current = null;
    };
  }, [open]);

  if (!open) return null;

  async function submit() {
    if (confirmation !== CONFIRMATION || deleting) return;
    const controller = new AbortController();
    controllerRef.current = controller;
    setDeleting(true);
    setError(null);
    try {
      const receipt = await deleteWalletCase(caseId, controller.signal);
      if (!controller.signal.aborted) onDeleted(receipt);
    } catch (caught) {
      if (controller.signal.aborted) return;
      setError(
        caught instanceof Error
          ? caught.message
          : "Wallet Case deletion failed.",
      );
      setDeleting(false);
      controllerRef.current = null;
    }
  }

  return (
    <div
      className="case-detail-backdrop"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !deleting) onClose();
      }}
    >
      <section
        className="case-delete-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="case-delete-title"
        aria-describedby="case-delete-description"
      >
        <header>
          <span><Trash size={21} weight="duotone" /></span>
          <div>
            <small>Permanent data lifecycle action</small>
            <h2 id="case-delete-title">Delete Wallet Case?</h2>
          </div>
          <button
            type="button"
            aria-label="Close deletion confirmation"
            disabled={deleting}
            onClick={onClose}
          >
            <X size={19} />
          </button>
        </header>

        <div className="case-delete-content">
          <p id="case-delete-description">
            <strong>{caseName}</strong> and its snapshots, normalized activity,
            evidence jobs, and saved report revisions will be permanently removed.
          </p>
          <div className="case-delete-boundary">
            <WarningCircle size={20} weight="fill" />
            <p>
              Active synchronization or evidence work must be cancelled first.
              A non-sensitive audit receipt containing only public IDs, time, and
              removal counts is retained.
            </p>
          </div>
          <label htmlFor="case-delete-confirmation">
            Type <strong>{CONFIRMATION}</strong> to confirm
          </label>
          <input
            ref={inputRef}
            id="case-delete-confirmation"
            value={confirmation}
            disabled={deleting}
            autoComplete="off"
            spellCheck={false}
            onChange={(event) => setConfirmation(event.target.value)}
          />
          {error && <p className="case-delete-error" role="alert">{error}</p>}
        </div>

        <footer>
          <button
            type="button"
            className="button-secondary"
            disabled={deleting}
            onClick={onClose}
          >
            Keep case
          </button>
          <button
            type="button"
            className="button-danger"
            disabled={confirmation !== CONFIRMATION || deleting}
            onClick={() => void submit()}
          >
            {deleting ? <SpinnerGap className="spin" size={17} /> : <Trash size={17} />}
            {deleting ? "Deleting…" : "Delete Wallet Case"}
          </button>
        </footer>
      </section>
    </div>
  );
}
