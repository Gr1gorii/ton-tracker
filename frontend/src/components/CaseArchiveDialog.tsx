import { useEffect, useRef, useState } from "react";
import {
  Archive,
  SpinnerGap,
  WarningCircle,
  X,
} from "@phosphor-icons/react";

import type { WalletCase } from "../walletCase";
import { archiveWalletCase } from "../walletCaseApi";

export default function CaseArchiveDialog({
  caseId,
  caseName,
  open,
  onClose,
  onArchived,
}: {
  caseId: string;
  caseName: string;
  open: boolean;
  onClose: () => void;
  onArchived: (walletCase: WalletCase) => void;
}) {
  const [archiving, setArchiving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const submitRef = useRef<HTMLButtonElement>(null);
  const controllerRef = useRef<AbortController | null>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    if (!open) return;
    setArchiving(false);
    setError(null);
    submitRef.current?.focus();
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
    if (archiving) return;
    const controller = new AbortController();
    controllerRef.current = controller;
    setArchiving(true);
    setError(null);
    try {
      const archived = await archiveWalletCase(caseId, controller.signal);
      if (!controller.signal.aborted) onArchived(archived);
    } catch (caught) {
      if (controller.signal.aborted) return;
      setError(caught instanceof Error ? caught.message : "Wallet Case archival failed.");
      setArchiving(false);
      controllerRef.current = null;
    }
  }

  return (
    <div
      className="case-detail-backdrop"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !archiving) onClose();
      }}
    >
      <section
        className="case-archive-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="case-archive-title"
        aria-describedby="case-archive-description"
      >
        <header>
          <span><Archive size={21} weight="duotone" /></span>
          <div>
            <small>Reversible workspace action</small>
            <h2 id="case-archive-title">Archive Wallet Case?</h2>
          </div>
          <button
            type="button"
            aria-label="Close archival confirmation"
            disabled={archiving}
            onClick={onClose}
          >
            <X size={19} />
          </button>
        </header>

        <div className="case-archive-content">
          <p id="case-archive-description">
            <strong>{caseName}</strong> will leave the active library. Its snapshots,
            Activity, Evidence, Findings, notes, and saved Reports stay intact.
          </p>
          <div className="case-archive-boundary">
            <Archive size={20} weight="fill" />
            <p>
              You can restore this Case from the Archived view. Active synchronization
              or evidence work must finish or be cancelled first.
            </p>
          </div>
          {error && (
            <p className="case-archive-error" role="alert">
              <WarningCircle size={17} weight="fill" /> {error}
            </p>
          )}
        </div>

        <footer>
          <button
            type="button"
            className="button-secondary"
            disabled={archiving}
            onClick={onClose}
          >
            Keep active
          </button>
          <button
            ref={submitRef}
            type="button"
            className="button-primary"
            disabled={archiving}
            onClick={() => void submit()}
          >
            {archiving ? <SpinnerGap className="spin" size={17} /> : <Archive size={17} />}
            {archiving ? "Archiving…" : "Archive Wallet Case"}
          </button>
        </footer>
      </section>
    </div>
  );
}
