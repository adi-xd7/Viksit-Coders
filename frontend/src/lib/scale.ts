/** A shared linear scale with "nice" ticks, computed from the data (never a fixed maximum).
 * The domain always includes 0 so a bar's position is read against zero. */
export interface Scale {
  min: number;
  max: number;
  ticks: number[];
  pos: (v: number) => number; // 0..100 (%)
}

export function niceStep(span: number, target = 4): number {
  if (!(span > 0)) return 1;
  const raw = span / target;
  const p = Math.pow(10, Math.floor(Math.log10(raw)));
  const f = raw / p;
  const nice = f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10;
  return nice * p;
}

export function linearScale(values: number[], target = 4): Scale {
  const finite = values.filter((v) => Number.isFinite(v));
  const lo = Math.min(0, ...finite);
  const hi = Math.max(0, ...finite);
  const step = niceStep(hi - lo || 1, target);
  const min = Math.floor(lo / step) * step;
  const max = Math.max(Math.ceil(hi / step) * step, min + step);
  const ticks: number[] = [];
  for (let t = min; t <= max + step / 2; t += step) ticks.push(Math.round(t * 1e6) / 1e6);
  return { min, max, ticks, pos: (v) => ((v - min) / (max - min)) * 100 };
}
