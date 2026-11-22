import { test } from "node:test";
import assert from "node:assert/strict";
import { chooseResults, rulesTable, lotSquares } from "../../site/lot-drawing/table.js";

const row = (o) => ({ rule: "lot_area", name: "Lot size", status: "fails", measured: 4000, required: 8000, unit: "sq ft", limit: "min", ...o });
const plain = { results: { label: "R-8 zone rules", rules: [row()] } };
const district = { district: "Cameron Station", results: { label: "Cameron Station approved plan", rules: [row({ status: "not_required", required: undefined, explanation: "site plan" })] },
                   ordinary: { label: "Ordinary R-8 zone", rules: [row()] } };

test("plain lots have no extra column", () => {
  assert.equal(chooseResults(plain, true).extra, null);
});
test("district lots swap sets with the switch", () => {
  assert.equal(chooseResults(district, false).main.label, "Cameron Station approved plan");
  assert.equal(chooseResults(district, false).extra.label, "Ordinary R-8 zone");
  assert.equal(chooseResults(district, true).main.label, "Ordinary R-8 zone");
  assert.equal(chooseResults(district, true).extra.label, "Cameron Station approved plan");
});
test("table shows labels, limits and tooltips", () => {
  const { main, extra } = chooseResults(district, false);
  const html = rulesTable(main, extra);
  assert.match(html, /data-rule="lot_area"/);
  assert.match(html, /NOT REQUIRED/);
  assert.match(html, /data-tip="site plan"/);
  assert.match(html, /Ordinary R-8 zone/);
  assert.match(html, /FAILS[^<]*<\/span>[^]*≥ 8,000 sq ft/);
});
test("text is escaped", () => {
  const html = rulesTable({ label: "x", rules: [row({ explanation: 'a "quote" <b>' })] }, null);
  assert.doesNotMatch(html, /<b>/);
});
test("squares are skipped without a minimum", () => {
  assert.equal(lotSquares(row({ required: undefined })), "");
  assert.match(lotSquares(row()), /<svg/);
});
test("summary rows span three columns, bars are skipped without numbers", () => {
  const html = rulesTable({ label: "x", rules: [
    { rule: "home_type", name: "Home type", status: "passes", summary: "twin house allowed in R-8" },
    row({ rule: "h", measured: undefined }),
  ] }, null);
  assert.match(html, /colspan="3"[^>]*>twin house allowed in R-8/);
  assert.doesNotMatch(html, /class="bar"/);
});
test("shares show as percent and extra cells fall back to a dash", () => {
  const main = { label: "m", rules: [row({ rule: "cov", unit: "share", limit: "max", measured: 0.42, required: 0.35 }), row({ rule: "only_main" })] };
  const extra = { label: "e", rules: [row({ rule: "cov", status: "passes" })] };
  const html = rulesTable(main, extra);
  assert.match(html, /42%/);
  assert.match(html, /≤ 35%/);
  assert.match(html, /col-extra[^>]*>–</);
});
test("squares only call the lot bigger when it is", () => {
  assert.match(lotSquares(row({ status: "passes", measured: 9000 })), /at least as big as the zone requires/);
  const close = lotSquares(row({ status: "passes", measured: 7800 }));
  assert.match(close, /slightly smaller than the zone requires, but within the map's margin/);
  assert.doesNotMatch(close, /as big as/);
  assert.match(lotSquares(row()), /50% of the land/);
  assert.doesNotMatch(lotSquares(row({ status: "not_checked", measured: 7800 })), /sq-note/);
});
test("only failing rows take keyboard focus", () => {
  const html = rulesTable({ label: "x", rules: [row(), row({ rule: "height", status: "passes" })] }, null);
  assert.match(html, /<tr data-rule="lot_area" tabindex="0">/);
  assert.match(html, /<tr data-rule="height">/);
});
test("older lots get their own pill, bar and squares, and keep the shortfall", () => {
  const older = row({ status: "older_lot", measured: 1800, required: 1980, explanation: "recorded before December 16, 2023" });
  const html = rulesTable({ label: "x", rules: [older] }, null);
  assert.match(html, /pill older explain[^>]*>OLDER LOT OK</);
  assert.match(html, /<i class="older"/);
  assert.match(html, /1,800 sq ft/);
  assert.match(html, /<tr data-rule="lot_area">/);
  const squares = lotSquares(older);
  assert.match(squares, /box older/);
  assert.match(squares, /91% of the land the zone asks of a new lot/);
});
