"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useSyncExternalStore } from "react";

const LINKS = [
  { href: "/", label: "Atlas" },
  { href: "/forecast", label: "Forecast Studio" },
  { href: "/models", label: "Model Lab" },
  { href: "/renewables", label: "Renewables" },
  { href: "/storage", label: "Storage Lab" },
  { href: "/track-record", label: "Track record" },
  { href: "/methods", label: "Methods & sources" },
];

type Theme = "system" | "light" | "dark";

// Theme lives in <html data-theme> (set before paint by the boot script in layout.tsx)
// and in localStorage; this tiny external store keeps React in sync without effects.
const listeners = new Set<() => void>();
const readTheme = (): Theme => (document.documentElement.getAttribute("data-theme") as Theme | null) ?? "system";
function writeTheme(t: Theme) {
  const el = document.documentElement;
  if (t === "system") el.removeAttribute("data-theme");
  else el.setAttribute("data-theme", t);
  try {
    localStorage.setItem("gm-theme", t);
  } catch {}
  listeners.forEach((l) => l());
}
const subscribe = (l: () => void) => {
  listeners.add(l);
  return () => listeners.delete(l);
};

function ThemeToggle() {
  const theme = useSyncExternalStore(subscribe, readTheme, () => "system" as Theme);
  const next: Record<Theme, Theme> = { system: "light", light: "dark", dark: "system" };
  return (
    <button
      onClick={() => writeTheme(next[theme])}
      className="rounded-md border border-border px-2.5 py-1 text-[12px] text-ink-2 hover:text-ink"
      aria-label={`Theme: ${theme}. Click to switch.`}
    >
      Theme: {theme}
    </button>
  );
}

export function Nav() {
  const path = usePathname();
  return (
    <header className="sticky top-0 z-20 border-b border-border bg-page/90 backdrop-blur">
      <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-x-6 gap-y-2 px-4 py-3">
        <Link href="/" className="flex items-baseline gap-2">
          <span className="text-[15px] font-semibold tracking-tight text-ink">GridMind</span>
          <span className="text-[12px] text-muted">DE-LU load intelligence</span>
        </Link>
        <nav aria-label="Main" className="order-3 -mx-1 flex w-full gap-1 overflow-x-auto sm:order-none sm:w-auto sm:flex-1">
          {LINKS.map((l) => {
            const active = l.href === "/" ? path === "/" : path.startsWith(l.href);
            return (
              <Link
                key={l.href}
                href={l.href}
                aria-current={active ? "page" : undefined}
                className={`whitespace-nowrap rounded-md px-2.5 py-1 text-[13px] ${
                  active ? "bg-surface-2 font-medium text-ink" : "text-ink-2 hover:text-ink"
                }`}
              >
                {l.label}
              </Link>
            );
          })}
        </nav>
        <ThemeToggle />
      </div>
    </header>
  );
}
