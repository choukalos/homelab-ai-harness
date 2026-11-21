/**
 * SVG chart helper tests (Slice 4, PLAN.md §6: server-rendered SVG, no
 * chart library). Sample data in, SVG string out.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { svgBarChart, svgHBarChart, type ChartBar } from "./charts.js";

test("svgBarChart renders one bar per data point with labels, values, and tooltips", () => {
  const bars: ChartBar[] = [
    { label: "Aug", value: 1.5 },
    { label: "Sep", value: 0 },
    { label: "Oct", value: 12.25 },
    { label: "Nov", value: 3.75 },
  ];
  const svg = svgBarChart(bars);
  assert.ok(svg.startsWith('<svg xmlns="http://www.w3.org/2000/svg"'), "svg root element");
  assert.ok(svg.includes('role="img"'), "accessible svg");
  assert.equal(svg.match(/<rect /g)?.length, 4, "one rect per bar");
  for (const b of bars) assert.ok(svg.includes(`>${b.label}<`), `x-axis label ${b.label}`);
  assert.ok(svg.includes("12.25"), "value label above the bar");
  assert.ok(svg.includes("<title>Oct: 12.25</title>"), "tooltip with label + value");
});

test("svgBarChart escapes HTML in labels and tooltips", () => {
  const svg = svgBarChart([{ label: "<b>Bad</b>", value: 1 }]);
  assert.ok(!svg.includes("<b>Bad</b>"), "raw HTML must not appear");
  assert.ok(svg.includes("&lt;b&gt;Bad&lt;/b&gt;"), "escaped label");
  assert.ok(svg.includes("<title>&lt;b&gt;Bad&lt;/b&gt;: 1.00</title>"), "escaped tooltip");
});

test("svgBarChart honors the custom value format", () => {
  const svg = svgBarChart([{ label: "Nov", value: 4.321 }], { formatValue: (n) => `$${n.toFixed(2)}` });
  assert.ok(svg.includes("$4.32"), "formatted value label");
  assert.ok(svg.includes("<title>Nov: $4.32</title>"), "formatted tooltip");
});

test("svgBarChart renders grid lines with max-value labels", () => {
  const svg = svgBarChart([{ label: "Nov", value: 10 }]);
  assert.ok(svg.includes("10"), "max on the top grid line");
  assert.ok(svg.includes("5"), "mid grid line at half of max");
  const lines = svg.match(/<line /g)?.length ?? 0;
  assert.equal(lines, 3, "grid at 0/50/100%");
});

test("svgBarChart empty and all-zero data render a no-data state without NaN", () => {
  const empty = svgBarChart([]);
  assert.ok(empty.includes("no data"), "empty state");
  const zeros = svgBarChart([
    { label: "Jan", value: 0 },
    { label: "Feb", value: 0 },
  ]);
  assert.ok(zeros.includes("no data"), "all-zero state");
  for (const svg of [empty, zeros, svgBarChart([{ label: "X", value: 7 }])]) {
    assert.ok(!svg.includes("NaN"), "no NaN in the output");
  }
});

test("svgHBarChart renders one row per entry with label, value, and sub", () => {
  const rows: ChartBar[] = [
    { label: "Alpha", value: 10, sub: "3 completed" },
    { label: "Beta", value: 0, sub: "0 completed" },
  ];
  const svg = svgHBarChart(rows);
  assert.equal(svg.match(/<rect /g)?.length, 2, "one rect per row");
  assert.ok(svg.includes(">Alpha<"), "row label");
  assert.ok(svg.includes("10.00"), "formatted value");
  assert.ok(svg.includes("3 completed"), "sub line next to the value");
  assert.ok(svg.includes("<title>Alpha: 10.00 (3 completed)</title>"), "tooltip");
});

test("svgHBarChart escapes labels and renders a no-data state when empty", () => {
  assert.ok(svgHBarChart([]).includes("no data"), "empty state");
  const svg = svgHBarChart([{ label: "a&b", value: 1 }]);
  assert.ok(svg.includes("a&amp;b"), "escaped label");
  assert.ok(!svg.includes("NaN"), "no NaN");
});
