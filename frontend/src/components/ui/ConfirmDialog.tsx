"use client";

/**
 * A real in-app replacement for window.confirm(). The browser's native
 * confirm() renders completely outside this app's control - unstyled,
 * unbranded, blocks the entire tab's JS thread while it's open, and reads
 * "<hostname> says" above whatever message is passed in. It's the single
 * most obvious "this wasn't designed" moment a user can hit, precisely
 * because every other interaction in the app is deliberately styled and
 * this one, by construction, cannot be.
 *
 * useConfirm() mirrors window.confirm's own call shape on purpose -
 * `if (!(await confirm({...}))) return;` reads almost identically to
 * `if (!window.confirm(...)) return;` - so every call site that used to
 * block on the browser's dialog now awaits this app's own tactile one
 * instead, with no change to the surrounding control flow.
 */
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { TriangleAlert } from "lucide-react";
import clsx from "clsx";
import { Button } from "./Button";

interface ConfirmOptions {
  title: string;
  message: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  // "danger" for anything destructive/irreversible (delete, retire) so the
  // confirm button picks up the same restrained red treatment as every
  // other destructive action in the app; "primary" for a confirmation
  // that isn't itself dangerous (e.g. reactivating an agent).
  variant?: "danger" | "primary";
}

interface ConfirmState extends ConfirmOptions {
  resolve: (value: boolean) => void;
}

const ConfirmContext = createContext<(opts: ConfirmOptions) => Promise<boolean>>(() =>
  Promise.resolve(false)
);

export function useConfirm() {
  return useContext(ConfirmContext);
}

export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<ConfirmState | null>(null);
  const [mounted, setMounted] = useState(false);
  const cancelRef = useRef<HTMLButtonElement>(null);

  useEffect(() => setMounted(true), []);

  const confirm = useCallback((opts: ConfirmOptions) => {
    return new Promise<boolean>((resolve) => {
      setState({ ...opts, resolve });
    });
  }, []);

  const close = useCallback((result: boolean) => {
    setState((s) => {
      s?.resolve(result);
      return null;
    });
  }, []);

  useEffect(() => {
    if (!state) return;
    // Cancel, not confirm, gets the initial focus - a destructive dialog
    // should never let a stray Enter keypress (e.g. from whatever the user
    // was just typing) land on the irreversible option by default.
    cancelRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [state, close]);

  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      {mounted &&
        state &&
        createPortal(
          <div className="fixed inset-0 z-[100] flex items-center justify-center p-4">
            <button
              type="button"
              aria-label="Cancel"
              onClick={() => close(false)}
              className="fixed inset-0 bg-black/50 backdrop-blur-[2px]"
            />
            <div
              role="alertdialog"
              aria-modal="true"
              aria-labelledby="confirm-dialog-title"
              aria-describedby="confirm-dialog-message"
              className="card-elevated animate-enter relative w-full max-w-sm p-5"
              style={{ boxShadow: "0 16px 40px rgba(0,0,0,0.28)" }}
            >
              <div className="flex items-start gap-3">
                <div
                  className={clsx(
                    "flex h-9 w-9 shrink-0 items-center justify-center rounded-lg",
                    state.variant === "danger"
                      ? "bg-[var(--color-danger-soft)] text-[var(--color-danger)]"
                      : "bg-[var(--color-accent-soft)] text-[var(--color-accent)]"
                  )}
                >
                  <TriangleAlert size={18} />
                </div>
                <div className="min-w-0 flex-1 pt-0.5">
                  <h2 id="confirm-dialog-title" className="text-[15px] font-semibold text-[var(--color-text)]">
                    {state.title}
                  </h2>
                  <p
                    id="confirm-dialog-message"
                    className="mt-1.5 text-sm leading-relaxed text-[var(--color-text-secondary)]"
                  >
                    {state.message}
                  </p>
                </div>
              </div>
              <div className="mt-5 flex justify-end gap-2">
                <Button ref={cancelRef} variant="secondary" onClick={() => close(false)}>
                  {state.cancelLabel || "Cancel"}
                </Button>
                <Button variant={state.variant === "danger" ? "danger" : "primary"} onClick={() => close(true)}>
                  {state.confirmLabel || "Confirm"}
                </Button>
              </div>
            </div>
          </div>,
          document.body
        )}
    </ConfirmContext.Provider>
  );
}
