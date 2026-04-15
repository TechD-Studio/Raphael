// Imperative confirm() replacement for Tauri v2 WKWebView where window.confirm()
// silently returns false. Mounts a lightweight React dialog into document.body
// and resolves a Promise<boolean> on user choice.

import { createRoot, type Root } from "react-dom/client";
import { useEffect, useState } from "react";

let root: Root | null = null;
let container: HTMLDivElement | null = null;

function ensureRoot(): Root {
  if (root) return root;
  container = document.createElement("div");
  container.id = "__confirm_root";
  document.body.appendChild(container);
  root = createRoot(container);
  return root;
}

type Opts = {
  message: string;
  okLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
};

function Dialog({
  opts,
  onResolve,
}: {
  opts: Opts;
  onResolve: (v: boolean) => void;
}) {
  const [visible, setVisible] = useState(true);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close(false);
      if (e.key === "Enter") close(true);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function close(v: boolean) {
    setVisible(false);
    setTimeout(() => onResolve(v), 50);
  }

  if (!visible) return null;
  return (
    <div className="approval-overlay" onClick={() => close(false)}>
      <div
        className="approval-dialog"
        onClick={(e) => e.stopPropagation()}
        style={{ minWidth: 360, maxWidth: 520 }}
      >
        <div
          className="approval-title"
          style={{
            color: opts.danger ? "#b91c1c" : "#1c1d20",
            whiteSpace: "pre-wrap",
          }}
        >
          {opts.message}
        </div>
        <div className="approval-actions">
          <button onClick={() => close(false)}>
            {opts.cancelLabel || "취소"}
          </button>
          <button
            className="primary"
            style={opts.danger ? { background: "#dc2626" } : undefined}
            onClick={() => close(true)}
            autoFocus
          >
            {opts.okLabel || "확인"}
          </button>
        </div>
      </div>
    </div>
  );
}

export function confirmDialog(
  message: string,
  options: Omit<Opts, "message"> = {},
): Promise<boolean> {
  return new Promise((resolve) => {
    const r = ensureRoot();
    const unmount = () => r.render(<></>);
    r.render(
      <Dialog
        opts={{ message, ...options }}
        onResolve={(v) => {
          unmount();
          resolve(v);
        }}
      />,
    );
  });
}
