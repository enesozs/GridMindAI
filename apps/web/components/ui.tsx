import type { ReactNode } from "react";

export function Panel({
  title,
  subtitle,
  children,
  footer,
  className = "",
}: {
  title: string;
  subtitle?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  className?: string;
}) {
  return (
    <section className={`rounded-xl border border-border bg-surface p-4 sm:p-5 ${className}`}>
      <header className="mb-3">
        <h2 className="text-[15px] font-semibold tracking-tight text-ink">{title}</h2>
        {subtitle && <p className="mt-0.5 text-[13px] text-ink-2">{subtitle}</p>}
      </header>
      {children}
      {footer && <footer className="mt-3 border-t border-border pt-2 text-[11px] text-muted">{footer}</footer>}
    </section>
  );
}

export function Stat({ label, value, note }: { label: string; value: string; note?: ReactNode }) {
  return (
    <div className="rounded-lg border border-border bg-surface px-4 py-3">
      <div className="text-[12px] text-ink-2">{label}</div>
      <div className="num mt-1 text-2xl font-semibold tracking-tight text-ink">{value}</div>
      {note && <div className="mt-0.5 text-[12px] text-muted">{note}</div>}
    </div>
  );
}

export function Skeleton({ height = 280 }: { height?: number }) {
  return (
    <div
      aria-busy="true"
      aria-label="Loading"
      className="animate-pulse rounded-lg bg-surface-2"
      style={{ height }}
    />
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="rounded-lg border border-border bg-surface-2 p-4 text-[13px] text-ink-2">
      <p className="font-medium text-ink">Could not load this data.</p>
      <p className="mt-1">{message}</p>
      <p className="mt-1">
        The site is static: data files are produced by the pipeline (<code>gridmind export</code>). If you are
        running locally, run the export first.
      </p>
      {onRetry && (
        <button onClick={onRetry} className="mt-3 rounded-md border border-border px-3 py-1.5 text-ink hover:bg-surface">
          Retry
        </button>
      )}
    </div>
  );
}

export function SourceNote({ children }: { children: ReactNode }) {
  return <span className="text-[11px] text-muted">{children}</span>;
}
