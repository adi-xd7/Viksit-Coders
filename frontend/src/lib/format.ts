const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "2027-01-25" -> "25 Jan 2027" (no time-zone shifts: the date is parsed as written). */
export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "";
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  if (!m) return iso;
  return `${Number(m[3])} ${MONTHS[Number(m[2]) - 1]} ${m[1]}`;
}

/** ISO timestamp -> "26 Oct 2026, 07:00 UTC" (always UTC, so the quota reset time is unambiguous). */
export function fmtTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const hh = String(d.getUTCHours()).padStart(2, "0");
  const mm = String(d.getUTCMinutes()).padStart(2, "0");
  return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}, ${hh}:${mm} UTC`;
}

export function monthLabel(year: number, month0: number, withYear: boolean): string {
  return withYear ? `${MONTHS[month0]} ${String(year).slice(2)}` : MONTHS[month0];
}

/** Days since epoch for a YYYY-MM-DD date (UTC, so it is stable everywhere). */
export function dayNum(iso: string): number {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  if (!m) return NaN;
  return Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3])) / 86_400_000;
}

export function fmtNum(n: number): string {
  return n.toLocaleString("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
}

export function cap(s: string): string {
  return s ? s[0].toUpperCase() + s.slice(1) : s;
}

/** Short citation label: "DOC P3" for a paragraph, "DOC R4" for a trade row. */
export function citeLabel(c: { doc_id: string; paragraph_ref?: string | null; row_id?: string | null }): string {
  if (c.row_id) return `${c.doc_id} ${c.row_id.split("#").pop()}`;
  return c.paragraph_ref ? `${c.doc_id} ${c.paragraph_ref}` : c.doc_id;
}
