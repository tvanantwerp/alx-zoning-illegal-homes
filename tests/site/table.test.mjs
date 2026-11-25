import { test } from "node:test";
import assert from "node:assert/strict";
import { chooseResults, rulesTable, lotSquares, notesList, verdict, permitsList } from "../../site/lot-drawing/table.js";

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
  assert.match(html, /<tr role="row" data-rule="lot_area" tabindex="0">/);
  assert.match(html, /<tr role="row" data-rule="height">/);
});
test("older lots get their own pill, bar and squares, and keep the shortfall", () => {
  const older = row({ status: "older_lot", measured: 1800, required: 1980, explanation: "recorded before December 16, 2023" });
  const html = rulesTable({ label: "x", rules: [older] }, null);
  assert.match(html, /pill older explain[^>]*>OLDER LOT OK</);
  assert.match(html, /<i class="older"/);
  assert.match(html, /1,800 sq ft/);
  assert.match(html, /<tr role="row" data-rule="lot_area">/);
  const squares = lotSquares(older);
  assert.match(squares, /box older/);
  assert.match(squares, /91% of the land the zone asks of a new lot/);
});
test("the verdict links to each failing row", () => {
  const html = verdict({ label: "x", rules: [row(), row({ rule: "yard:rear", name: "Rear yard" }), row({ rule: "height", status: "passes" })] });
  assert.match(html, /^Breaks 2 rules: /);
  assert.match(html, /<button type="button" class="jump" data-jump="lot_area">Lot size<\/button>,<\/span>/);
  assert.match(html, /data-jump="yard:rear">Rear yard</);
  assert.doesNotMatch(html, /data-jump="height"/);
});
test("a lot that passes gets a plain verdict", () => {
  assert.equal(verdict({ label: "x", rules: [row({ status: "passes" })] }), "Passes every rule the map checks");
  assert.match(verdict({ label: "x", rules: [row()] }), /^Breaks 1 rule: /);
});
test("cells carry labels for the narrow-screen layout", () => {
  const { main, extra } = chooseResults(district, true);
  const html = rulesTable(main, extra);
  assert.match(html, /<td role="cell" class="col-measured num" data-label="Measured">/);
  assert.match(html, /<td role="cell" class="col-says num" data-label="Rule says">/);
  assert.match(html, /<td role="cell" class="col-extra" data-label="Cameron Station approved plan">/);
});
test("table parts name their roles, so screen readers keep the table on narrow screens", () => {
  const { main, extra } = chooseResults(district, true);
  const html = rulesTable(main, extra);
  assert.match(html, /<table class="report" role="table"><thead role="rowgroup"><tr role="row"><th role="columnheader">Rule<\/th>/);
  assert.match(html, /<tbody role="rowgroup">/);
  assert.doesNotMatch(html, /<td[ >](?!role="cell")/);
  assert.doesNotMatch(html, /<th[ >](?!role="columnheader")/);
});

test("notes show repeated text once, in first-seen order", () => {
  assert.equal(notesList(["A roof crosses the lot line.", "Another note.", "A roof crosses the lot line."]),
    '<ul class="notes"><li>A roof crosses the lot line.</li><li>Another note.</li></ul>');
});

test("permit rows read as passing and name the case", () => {
  const r = row({ status: "permit_on_file", permit: { case: "SUP2010-00005", how: "parcel" } });
  const html = rulesTable({ label: "x", rules: [r] }, null);
  assert.match(html, /PERMIT ON FILE/);
  assert.match(html, /class="pill permit/);
  assert.equal(verdict({ rules: [r] }), "Passes every rule the map checks");
});
test("a permit row with no documents links its case to the city search", () => {
  const r = row({ status: "permit_on_file", permit: { case: "SUP2010-00005", how: "parcel" } });
  const permits = [{ case: "SUP2010-00005", links: [], search_url: "https://imaging.alexandriava.gov/s" }];
  const html = rulesTable({ label: "x", rules: [r] }, null, permits);
  assert.match(html, /<a [^>]*href="https:\/\/imaging.alexandriava.gov\/s"[^>]*>SUP2010-00005<\/a>/);
});
test("a permit row links its case to the case's first document", () => {
  const r = row({ status: "permit_on_file", permit: { case: "SUP2010-00005", how: "parcel" } });
  const permits = [{ case: "SUP2010-00005", links: [{ name: "a", url: "https://imaging.alexandriava.gov/d" }] }];
  const html = rulesTable({ label: "x", rules: [r] }, null, permits);
  assert.match(html, /<a [^>]*href="https:\/\/imaging.alexandriava.gov\/d"[^>]*>SUP2010-00005<\/a>/);
});
test("permits list links each case to the city", () => {
  const html = permitsList([{ case: "SUP2005-00035", kind: "SUP", year: 2005, description: "convenience store",
    grants: ["lot_area", "yard:left"], links: [{ name: "Staff report", url: "https://imaging.alexandriava.gov/x" }],
    search_url: "https://imaging.alexandriava.gov/s" }], { lot_area: "Lot size", "yard:left": "Left side yard" });
  assert.match(html, /Permits and approvals on file/);
  assert.match(html, /href="https:\/\/imaging.alexandriava.gov\/x"/);
  assert.match(html, /special use permit/);
  assert.match(html, /2005/);
  assert.match(html, /Settles: Lot size, Left side yard/);
});
test("a case with no documents links to the city search", () => {
  const html = permitsList([{ case: "BZA2001-00001", kind: "BZA", year: null, description: "", grants: [], links: [],
    search_url: "https://imaging.alexandriava.gov/s?a=1&b=2" }]);
  assert.match(html, /href="https:\/\/imaging.alexandriava.gov\/s\?a=1&amp;b=2"/);
  assert.match(html, /Board of Zoning Appeals case/);
  assert.doesNotMatch(html, /Settles|null/);
});
test("no permits, no section", () => {
  assert.equal(permitsList([]), null);
  assert.equal(permitsList(undefined), null);
});
test("permit on file keeps the shortfall in the bar and squares", () => {
  const on = row({ status: "permit_on_file", measured: 3000, required: 8000, explanation: "SUP1" });
  assert.match(rulesTable({ label: "x", rules: [on] }, null), /<i class="older"/);
  assert.match(lotSquares(on), /box older/);
});
