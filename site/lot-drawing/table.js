import { esc, showValue, sqft, pct } from "./format.js";

const LABELS = {
  fails: "FAILS",
  passes: "PASSES",
  not_checked: "NOT CHECKED",
  no_rule: "NO RULE",
  not_required: "NOT REQUIRED",
};
const PILL_CLASS = { fails: "fail", passes: "pass", not_checked: "skip", no_rule: "none", not_required: "notreq" };

/** Which result set the main columns show, and which the extra column shows. */
export function chooseResults(lot, ordinary) {
  if (!lot.district || !lot.ordinary) return { main: lot.results, extra: null };
  return ordinary
    ? { main: lot.ordinary, extra: lot.results }
    : { main: lot.results, extra: lot.ordinary };
}

/** The status word as a coloured pill. A row with an explanation gets a hover tip. */
function pill(row) {
  const cls = PILL_CLASS[row.status] || "skip";
  const label = LABELS[row.status] || esc(row.status);
  return row.explanation
    ? `<span class="pill ${cls} explain" tabindex="0" data-tip="${esc(row.explanation)}">${label}</span>`
    : `<span class="pill ${cls}">${label}</span>`;
}

/** "≥ 8,000 sq ft" or "≤ 35%", or a dash when the row has no limit. */
function ruleSays(row) {
  if (row.required == null) return "–";
  return (row.limit === "max" ? "≤ " : "≥ ") + showValue(row.required, row.unit);
}

/** The measured value against the limit, with a mark at the limit. Red when the row fails. */
function bar(row) {
  if (row.measured == null || row.required == null) return "";
  const scale = Math.max(row.measured, row.required) * 1.15 || 1;
  const cls = row.status === "fails" ? "fail" : "";
  return `<div class="bar"><i class="${cls}" style="width:${(row.measured / scale) * 100}%"></i><b style="left:${(row.required / scale) * 100}%"></b></div>`;
}

/** Every rule the map checks, with the result, the numbers and a bar. */
export function rulesTable(main, extra) {
  const extraByRule = new Map((extra ? extra.rules : []).map((r) => [r.rule, r]));
  const head = `<th>Rule</th><th>Result</th><th>Measured</th><th>Rule says</th><th class="col-bar"></th>`
    + (extra ? `<th class="col-extra">${esc(extra.label)}</th>` : "");
  const body = main.rules.map((row) => {
    const name = row.about
      ? `<span class="explain" tabindex="0" data-tip="${esc(row.about)}">${esc(row.name)}</span>`
      : esc(row.name);
    const middle = row.summary
      ? `<td colspan="3">${esc(row.summary)}</td>`
      : `<td class="num">${row.measured == null ? "–" : showValue(row.measured, row.unit)}</td><td class="num">${ruleSays(row)}</td><td class="col-bar">${bar(row)}</td>`;
    let extraCell = "";
    if (extra) {
      const other = extraByRule.get(row.rule);
      extraCell = other
        ? `<td class="col-extra">${pill(other)}${other.summary ? "" : ` ${ruleSays(other)}`}</td>`
        : `<td class="col-extra">–</td>`;
    }
    return `<tr data-rule="${esc(row.rule)}"><td>${name}</td><td>${pill(row)}</td>${middle}${extraCell}</tr>`;
  });
  return `<div class="report-wrap"><table class="report"><thead><tr>${head}</tr></thead><tbody>${body.join("")}</tbody></table></div>`;
}

/** Two squares drawn to the same scale: this lot and the smallest lot allowed. */
export function lotSquares(row) {
  if (row.required == null || row.measured == null) return "";
  const fails = row.status === "fails";
  const max = Math.max(row.measured, row.required);
  const box = (area, cls, label) => {
    const side = Math.max(18, Math.sqrt(area / max) * 170);
    return `<div class="sq"><svg class="box ${cls}" width="${side}" height="${side}" viewBox="0 0 ${side} ${side}" aria-hidden="true"><rect x="1" y="1" width="${side - 2}" height="${side - 2}"/></svg><span>${label}<br><b>${sqft(area)}</b></span></div>`;
  };
  const note = fails
    ? `This lot has ${pct(row.measured / row.required)} of the land the zone requires.`
    : `This lot is bigger than the zone requires.`;
  return `<div class="inset lot-squares" data-rule="${esc(row.rule)}"><div class="inset-title">Lot size, drawn to scale</div><div class="squares">${box(row.measured, "", "This lot")}${box(row.required, fails ? "over" : "ghost", "Smallest allowed")}</div><p class="sq-note">${note}</p></div>`;
}

/** The lot's notes as a list. */
export function notesList(notes) {
  if (!notes || !notes.length) return "";
  return `<ul class="notes">${notes.map((n) => `<li>${esc(n)}</li>`).join("")}</ul>`;
}
