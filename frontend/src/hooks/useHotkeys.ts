import { useEffect } from "react";

/** Page-level single-key shortcuts. Ignored while typing in a field or with a modifier held.
 *  The handler returns true when it used the key. */
export function useHotkeys(handler: (e: KeyboardEvent) => boolean) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey || e.defaultPrevented) return;
      const t = e.target as HTMLElement | null;
      if (t && (t.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName))) return;
      if (document.querySelector("[data-modal-open]")) return;
      if (handler(e)) e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [handler]);
}
