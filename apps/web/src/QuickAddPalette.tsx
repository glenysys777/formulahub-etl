import { useEffect, useMemo, useRef, useState } from "react";
import { ComponentGlyph, categoryForType } from "./EtlNode";
import type { ComponentInfo } from "./api";

type Props = {
  open: boolean;
  query: string;
  onQueryChange: (q: string) => void;
  components: ComponentInfo[];
  onPick: (comp: ComponentInfo) => void;
  onClose: () => void;
};

function displayLabel(c: ComponentInfo): string {
  if (c.type === "tmap") return "Field Mapper";
  if (c.type === "column_map") return "Schema Map";
  return c.display_name || c.type;
}

export function QuickAddPalette({
  open,
  query,
  onQueryChange,
  components,
  onPick,
  onClose,
}: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [active, setActive] = useState(0);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return components.slice(0, 12);
    return components
      .filter((c) => {
        const label = displayLabel(c).toLowerCase();
        return (
          label.includes(q) ||
          c.type.toLowerCase().includes(q) ||
          (c.category || "").toLowerCase().includes(q)
        );
      })
      .slice(0, 14);
  }, [components, query]);

  useEffect(() => {
    setActive(0);
  }, [query, open]);

  useEffect(() => {
    if (!open) return;
    const t = window.setTimeout(() => inputRef.current?.focus(), 0);
    return () => window.clearTimeout(t);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        e.stopPropagation();
        onClose();
        return;
      }
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setActive((i) => Math.min(i + 1, Math.max(0, filtered.length - 1)));
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setActive((i) => Math.max(i - 1, 0));
        return;
      }
      if (e.key === "Enter") {
        e.preventDefault();
        const pick = filtered[active];
        if (pick) onPick(pick);
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [open, filtered, active, onPick, onClose]);

  if (!open) return null;

  return (
    <div
      className="quick-add-overlay"
      role="dialog"
      aria-modal="true"
      aria-label="Quick add component"
      data-testid="quick-add-palette"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="quick-add-modal">
        <div className="quick-add-head">
          <span className="quick-add-kicker">Type to place</span>
          <span className="quick-add-esc">Esc</span>
        </div>
        <input
          ref={inputRef}
          className="quick-add-input"
          value={query}
          onChange={(e) => onQueryChange(e.target.value)}
          placeholder="Filter components…"
          aria-label="Filter components"
          data-testid="quick-add-input"
          autoComplete="off"
          spellCheck={false}
        />
        <ul className="quick-add-list" role="listbox">
          {filtered.map((c, i) => {
            const cat = categoryForType(c.type);
            const label = displayLabel(c);
            return (
              <li key={c.type}>
                <button
                  type="button"
                  role="option"
                  aria-selected={i === active}
                  className={`quick-add-item cat-${cat}${i === active ? " active" : ""}`}
                  data-testid={`quick-add-item-${c.type}`}
                  onMouseEnter={() => setActive(i)}
                  onClick={() => onPick(c)}
                >
                  <span className="quick-add-icon">
                    <ComponentGlyph type={c.type} size={14} />
                  </span>
                  <span className="quick-add-label">{label}</span>
                  <span className="quick-add-type">{c.type}</span>
                </button>
              </li>
            );
          })}
          {!filtered.length && (
            <li className="quick-add-empty">No components match “{query}”</li>
          )}
        </ul>
        <p className="quick-add-hint">
          Focus the canvas, then type. Arrow keys · Enter to place · Esc to close.
        </p>
      </div>
    </div>
  );
}
