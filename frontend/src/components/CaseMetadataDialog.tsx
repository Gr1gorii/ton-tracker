import { useEffect, useRef, useState } from "react";
import {
  FloppyDisk,
  PencilSimple,
  SpinnerGap,
  WarningCircle,
  X,
} from "@phosphor-icons/react";

import type { WalletCase } from "../walletCase";
import {
  WalletCaseApiError,
  updateWalletCaseMetadata,
} from "../walletCaseApi";

function cleaned(value: string): string | null {
  const trimmed = value.trim();
  return trimmed || null;
}

export default function CaseMetadataDialog({
  walletCase,
  open,
  onClose,
  onUpdated,
}: {
  walletCase: WalletCase;
  open: boolean;
  onClose: () => void;
  onUpdated: (updated: WalletCase) => void;
}) {
  const [label, setLabel] = useState("");
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const controllerRef = useRef<AbortController | null>(null);
  const onCloseRef = useRef(onClose);
  const onUpdatedRef = useRef(onUpdated);
  onCloseRef.current = onClose;
  onUpdatedRef.current = onUpdated;

  useEffect(() => {
    if (!open) return;
    setLabel(walletCase.label ?? "");
    setNote(walletCase.note ?? "");
    setSaving(false);
    setError(null);
    inputRef.current?.focus();
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape" && !controllerRef.current) {
        onCloseRef.current();
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      controllerRef.current?.abort();
      controllerRef.current = null;
    };
  }, [open, walletCase.public_id]);

  if (!open) return null;

  const canonicalLabel = cleaned(label);
  const canonicalNote = cleaned(note);
  const changed = canonicalLabel !== walletCase.label || canonicalNote !== walletCase.note;

  async function submit() {
    if (!changed || saving) return;
    const controller = new AbortController();
    controllerRef.current = controller;
    setSaving(true);
    setError(null);
    try {
      const updated = await updateWalletCaseMetadata(
        walletCase,
        {
          expected_metadata_version: walletCase.metadata_version,
          label: canonicalLabel,
          note: canonicalNote,
        },
        controller.signal,
      );
      if (controller.signal.aborted) return;
      controllerRef.current = null;
      setSaving(false);
      onUpdatedRef.current(updated);
    } catch (caught) {
      if (controller.signal.aborted) return;
      controllerRef.current = null;
      setSaving(false);
      if (
        caught instanceof WalletCaseApiError &&
        caught.code === "case_metadata_changed"
      ) {
        setError(
          "This Case changed in another tab. Close and reopen the editor to load the current details.",
        );
      } else {
        setError(
          caught instanceof Error
            ? caught.message
            : "Wallet Case details could not be saved.",
        );
      }
    }
  }

  return (
    <div
      className="case-detail-backdrop"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !saving) onCloseRef.current();
      }}
    >
      <section
        className="case-metadata-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="case-metadata-title"
        aria-describedby="case-metadata-description"
      >
        <header>
          <span><PencilSimple size={21} weight="duotone" /></span>
          <div>
            <small>Case details</small>
            <h2 id="case-metadata-title">Edit Wallet Case</h2>
          </div>
          <button
            type="button"
            aria-label="Close Case editor"
            disabled={saving}
            onClick={() => onCloseRef.current()}
          >
            <X size={19} />
          </button>
        </header>

        <div className="case-metadata-content">
          <p id="case-metadata-description">
            Labels and notes organize this local Case. They do not change its
            canonical wallet, network, evidence, or saved reports.
          </p>
          <label htmlFor="case-metadata-label">
            <span>Label</span><small>{label.length}/120</small>
          </label>
          <input
            ref={inputRef}
            id="case-metadata-label"
            aria-label="Label"
            value={label}
            maxLength={120}
            disabled={saving}
            autoComplete="off"
            onChange={(event) => setLabel(event.target.value)}
          />
          <label htmlFor="case-metadata-note">
            <span>Note</span><small>{note.length}/4000</small>
          </label>
          <textarea
            id="case-metadata-note"
            aria-label="Note"
            value={note}
            maxLength={4_000}
            rows={7}
            disabled={saving}
            onChange={(event) => setNote(event.target.value)}
          />
          {error && (
            <div className="case-metadata-error" role="alert">
              <WarningCircle size={18} weight="fill" />
              <span>{error}</span>
            </div>
          )}
        </div>

        <footer>
          <button
            type="button"
            className="button-secondary"
            disabled={saving}
            onClick={() => onCloseRef.current()}
          >
            Cancel
          </button>
          <button
            type="button"
            className="button-primary"
            disabled={!changed || saving}
            onClick={() => void submit()}
          >
            {saving ? <SpinnerGap className="spin" size={17} /> : <FloppyDisk size={17} />}
            {saving ? "Saving…" : "Save details"}
          </button>
        </footer>
      </section>
    </div>
  );
}
