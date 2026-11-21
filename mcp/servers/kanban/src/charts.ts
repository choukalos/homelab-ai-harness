/**
 * Server-rendered SVG chart helpers (PLAN.md §6 Slice 4: "Charts =
 * server-rendered SVG (no chart library)"). Pure functions: data in, SVG
 * string out — embedded directly in the HTML templates (src/http/templates.ts).
 *
 * Dark-theme palette matches the GUI (background #161a22, grid #262b36,
 * bar #3b82f6, text #9ca3af/#e5e7eb).
 */

export interface ChartBar {
  /** Axis label (e.g. "Nov", project name). */
  label: string;
  value: number;
  /** Optional second line shown in the tooltip / next to the bar. */
  sub?: string;
}

export interface BarChartOptions {
  width?: number;
  height?: number;
  /** Format the value shown above/next to a bar (default: toFixed(2)). */
  formatValue?: (n: number) => string;
}

const C = {
  grid: "#262b36",
  bar: "#3b82f6",
  barZero: "#262b36",
  text: "#9ca3af",
  textStrong: "#e5e7eb",
  empty: "#6b7280",
} as const;

function esc(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function num(n: number): string {
  return Number.isFinite(n) ? String(Math.round(n * 100) / 100) : "0";
}

/**
 * Vertical bar chart (e.g. $ spend per month, rolling 12 months).
 * Bars scale to the max value; zero/empty data renders an empty-state
 * note instead of degenerate SVG.
 */
export function svgBarChart(bars: ChartBar[], opts: BarChartOptions = {}): string {
  const width = opts.width ?? 760;
  const height = opts.height ?? 240;
  const fmt = opts.formatValue ?? ((n: number) => n.toFixed(2));
  const padL = 48;
  const padR = 8;
  const padT = 26;
  const padB = 30;
  const innerW = width - padL - padR;
  const innerH = height - padT - padB;
  const baseline = padT + innerH;

  const max = bars.reduce((m, b) => Math.max(m, b.value), 0);
  if (bars.length === 0 || max <= 0) {
    return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="bar chart">
  <rect x="0" y="0" width="${width}" height="${height}" fill="none"/>
  <line x1="${padL}" y1="${baseline}" x2="${width - padR}" y2="${baseline}" stroke="${C.grid}" stroke-width="1"/>
  <text x="${width / 2}" y="${height / 2}" fill="${C.empty}" font-size="13" text-anchor="middle">no data</text>
</svg>`;
  }

  const slot = innerW / bars.length;
  const barW = Math.min(slot * 0.68, 56);
  const yFor = (v: number) => padT + innerH * (1 - v / max);

  // Grid lines at 0/50/100% of max with value labels.
  const grid = [0, 0.5, 1]
    .map((f) => {
      const y = num(padT + innerH * (1 - f));
      const label = num(max * f);
      return `  <line x1="${padL}" y1="${y}" x2="${width - padR}" y2="${y}" stroke="${C.grid}" stroke-width="1"/>
  <text x="${padL - 6}" y="${num(Number(y) + 4)}" fill="${C.text}" font-size="10" text-anchor="end">${esc(label)}</text>`;
    })
    .join("\n");

  const rects = bars
    .map((b, i) => {
      const x = padL + slot * i + (slot - barW) / 2;
      const y = yFor(b.value);
      const h = Math.max(baseline - y, b.value > 0 ? 1.5 : 0);
      const cx = num(Number(x) + barW / 2);
      const fill = b.value > 0 ? C.bar : C.barZero;
      const tip = `${b.label}: ${fmt(b.value)}${b.sub ? ` (${b.sub})` : ""}`;
      return `  <rect x="${num(x)}" y="${num(y)}" width="${num(barW)}" height="${num(h)}" rx="2" fill="${fill}">
    <title>${esc(tip)}</title>
  </rect>
  <text x="${cx}" y="${num(Number(y) - 5)}" fill="${C.textStrong}" font-size="10" text-anchor="middle">${esc(fmt(b.value))}</text>
  <text x="${cx}" y="${baseline + 14}" fill="${C.text}" font-size="10" text-anchor="middle">${esc(b.label)}</text>`;
    })
    .join("\n");

  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="bar chart" style="max-width:100%;height:auto">
${grid}
${rects}
</svg>`;
}

/**
 * Horizontal bar chart (e.g. per-project $ spend with completed counts).
 * One row per entry: label on the left, bar scaled to the max value,
 * formatted value + optional sub line on the right.
 */
export function svgHBarChart(rows: ChartBar[], opts: BarChartOptions = {}): string {
  const width = opts.width ?? 760;
  const rowH = 26;
  const padT = 6;
  const padB = 6;
  const labelW = 170;
  const valueW = 130;
  const height = padT + padB + rows.length * rowH;
  const fmt = opts.formatValue ?? ((n: number) => n.toFixed(2));

  if (rows.length === 0) {
    return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${Math.max(height, 40)}" role="img" aria-label="bar chart">
  <text x="${width / 2}" y="24" fill="${C.empty}" font-size="13" text-anchor="middle">no data</text>
</svg>`;
  }

  const max = rows.reduce((m, r) => Math.max(m, r.value), 0);
  const barMax = width - labelW - valueW - 16;
  const body = rows
    .map((r, i) => {
      const y = padT + i * rowH;
      const cy = y + rowH / 2;
      const w = max > 0 ? (r.value / max) * barMax : 0;
      const fill = r.value > 0 ? C.bar : C.barZero;
      const tip = `${r.label}: ${fmt(r.value)}${r.sub ? ` (${r.sub})` : ""}`;
      return `  <text x="${labelW - 8}" y="${num(Number(cy) + 4)}" fill="${C.textStrong}" font-size="12" text-anchor="end">${esc(r.label)}</text>
  <rect x="${labelW}" y="${num(cy - 6)}" width="${num(Math.max(w, r.value > 0 ? 2 : 0))}" height="12" rx="2" fill="${fill}">
    <title>${esc(tip)}</title>
  </rect>
  <text x="${labelW + Math.max(w, 0) + 8}" y="${num(Number(cy) + 4)}" fill="${C.text}" font-size="11">${esc(fmt(r.value))}${
        r.sub ? ` · ${esc(r.sub)}` : ""
      }</text>`;
    })
    .join("\n");

  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="bar chart" style="max-width:100%;height:auto">
${body}
</svg>`;
}
