import type { ReactNode } from "react";

/** Section: small uppercase label with a 1px ink rule under it. */
export function Section({ title, right, children, id, className = "mt-8" }: {
  title: string; right?: ReactNode; children: ReactNode; id?: string; className?: string;
}) {
  return (
    <section id={id} className={className} aria-label={title}>
      <div className="flex flex-wrap items-baseline justify-between gap-3 border-b border-ink pb-2">
        <h2 className="label m-0">{title}</h2>
        {right && <span className="text-xs text-ink-3">{right}</span>}
      </div>
      {children}
    </section>
  );
}

export function ViewHead({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <>
      <h1 className="m-0 mb-1 text-[20px] font-semibold leading-tight tracking-[-0.015em] text-balance">{title}</h1>
      {children && <p className="m-0 mb-5 max-w-[68ch] text-ink-2">{children}</p>}
    </>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="m-0 border-b border-rule py-3 text-ink-2">{children}</p>;
}

/** Alert: a ruled band; red only for failures. */
export function Alert({ tone = "info", title, children }: { tone?: "info" | "bad"; title: string; children?: ReactNode }) {
  const bad = tone === "bad";
  return (
    <div role={bad ? "alert" : "status"}
      className={`mb-5 border-l-2 py-2 pl-3 ${bad ? "border-bad bg-bad-wash" : "border-rule-2 bg-paper"}`}>
      <div className={`font-medium ${bad ? "text-bad" : "text-ink"}`}>{title}</div>
      {children && <div className="mt-1 text-[13px] text-ink-2">{children}</div>}
    </div>
  );
}

/** Loading placeholder: ruled grey rows (no animation beyond a gentle pulse). */
export function Skeleton({ rows = 4, label = "Loading" }: { rows?: number; label?: string }) {
  return (
    <div role="status" aria-label={label} className="mt-4">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="border-b border-rule py-3">
          <div className="h-2.5 w-24 animate-pulse rounded-sm bg-rule" />
          <div className="mt-2 h-3 animate-pulse rounded-sm bg-rule" style={{ width: `${88 - (i % 3) * 17}%` }} />
        </div>
      ))}
      <span className="sr-only">{label}…</span>
    </div>
  );
}

/** Segmented text filter (aria-pressed buttons with an ink underline when on). */
export function Filters<T extends string>({ value, options, onChange, label }: {
  value: T; options: [T, string][]; onChange: (v: T) => void; label: string;
}) {
  return (
    <div role="group" aria-label={label} className="flex flex-wrap gap-x-4 gap-y-1 text-[13px]">
      {options.map(([k, text]) => (
        <button key={k} type="button" aria-pressed={value === k} onClick={() => onChange(k)}
          className={`border-b-[1.5px] py-1 ${value === k ? "border-ink font-medium text-ink" : "border-transparent text-ink-2 hover:text-ink"}`}>
          {text}
        </button>
      ))}
    </div>
  );
}
