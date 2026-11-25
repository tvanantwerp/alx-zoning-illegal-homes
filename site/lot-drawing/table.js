import { esc, showValue, sqft, pct } from "./format.js";

const LABELS = {
  fails: "FAILS",
  passes: "PASSES",
  not_checked: "NOT CHECKED",
  no_rule: "NO RULE",
  not_required: "NOT REQUIRED",
  older_lot: "OLDER LOT OK",
  permit_on_file: "PERMIT ON FILE",
};
const PILL_CLASS = {
  fails: "fail", passes: "pass", not_checked: "skip", no_rule: "none", not_required: "notreq",
  older_lot: "older", permit_on_file: "permit",
};

/** Which result set the main columns show, and which the extra column shows. */
export function chooseResults(lot, ordinary) {
  if (!lot.district || !lot.ordinary) return { main: lot.results, extra: null };
  return ordinary
    ? { main: lot.ordinary, extra: lot.results }
    : { main: lot.results, extra: lot.ordinary };
}

/** The first document of the case with this number, or null when the lot has no such case on file. */
function caseLink(permits, number) {
  const found = (permits || []).find((p) => p.case === number);
  return found && found.links && found.links.length ? found.links[0].url : null;
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

/**
 * The measured value against the limit, with a mark at the limit. Red when the row fails,
 * and in the older-lot colour when the rule for older lots excuses a shortfall.
 */
function bar(row) {
  if (row.measured == null || row.required == null) return "";
  const scale = Math.max(row.measured, row.required) * 1.15 || 1;
  const cls = { fails: "fail", older_lot: "older" }[row.status] || "";
  return `<div class="bar"><i class="${cls}" style="width:${(row.measured / scale) * 100}%"></i><b style="left:${(row.required / scale) * 100}%"></b></div>`;
}

/**
 * The header's verdict: how many rules the lot breaks, with each one's name as a
 * button (`data-jump` holds the rule) that takes the reader to its row in the table.
 */
export function verdict(main) {
  const broken = main.rules.filter((row) => row.status === "fails");
  if (!broken.length) return "Passes every rule the map checks";
  // Each comma stays on the same line as the name before it.
  const links = broken.map((row, i) =>
    `<span class="jump-item"><button type="button" class="jump" data-jump="${esc(row.rule)}">${esc(row.name)}</button>`
    + `${i < broken.length - 1 ? "," : ""}</span>`);
  return `Breaks ${broken.length} rule${broken.length === 1 ? "" : "s"}: ${links.join(" ")}`;
}

/**
 * Every rule the map checks, with the result, the numbers and a bar.
 * Cells carry a class and a `data-label` naming their column, so narrow screens
 * can lay each row out as a small card instead of a wide table. A row settled by a
 * permit links its case number to the case's first document when `permits` has one. The table roles
 * are spelled out because some browsers stop reporting a table to screen readers
 * once CSS changes how its parts are laid out.
 */
export function rulesTable(main, extra, permits) {
  const extraByRule = new Map((extra ? extra.rules : []).map((r) => [r.rule, r]));
  const th = (text, cls) => `<th role="columnheader"${cls ? ` class="${cls}"` : ""}>${text}</th>`;
  const head = th("Rule") + th("Result") + th("Measured") + th("Rule says") + th("", "col-bar")
    + (extra ? th(esc(extra.label), "col-extra") : "");
  const extraLabel = extra ? ` data-label="${esc(extra.label)}"` : "";
  const body = main.rules.map((row) => {
    const number = row.permit && row.permit.case;
    const url = number && caseLink(permits, number);
    const permitNote = number
      ? `<div class="permit-note">Permit: ${url ? `<a href="${esc(url)}" target="_blank" rel="noopener">${esc(number)}</a>` : esc(number)}</div>`
      : "";
    const name = row.about
      ? `<span class="explain" tabindex="0" data-tip="${esc(row.about)}">${esc(row.name)}</span>`
      : esc(row.name);
    const nameCell = name + permitNote;
    const middle = row.summary
      ? `<td role="cell" class="col-summary" colspan="3">${esc(row.summary)}</td>`
      : `<td role="cell" class="col-measured num" data-label="Measured">${row.measured == null ? "–" : showValue(row.measured, row.unit)}</td>`
        + `<td role="cell" class="col-says num" data-label="Rule says">${ruleSays(row)}</td><td role="cell" class="col-bar">${bar(row)}</td>`;
    let extraCell = "";
    if (extra) {
      const other = extraByRule.get(row.rule);
      extraCell = other
        ? `<td role="cell" class="col-extra"${extraLabel}>${pill(other)}${other.summary ? "" : ` ${ruleSays(other)}`}</td>`
        : `<td role="cell" class="col-extra"${extraLabel}>–</td>`;
    }
    // Failing rows take keyboard focus so their part of the drawing can be highlighted without a mouse.
    const focus = row.status === "fails" ? ` tabindex="0"` : "";
    return `<tr role="row" data-rule="${esc(row.rule)}"${focus}><td role="cell" class="col-name">${nameCell}</td><td role="cell" class="col-result">${pill(row)}</td>${middle}${extraCell}</tr>`;
  });
  return `<div class="report-wrap"><table class="report" role="table"><thead role="rowgroup"><tr role="row">${head}</tr></thead>`
    + `<tbody role="rowgroup">${body.join("")}</tbody></table></div>`;
}

/** Two squares drawn to the same scale: this lot and the smallest lot allowed. */
export function lotSquares(row) {
  if (row.required == null || row.measured == null) return "";
  const fails = row.status === "fails";
  const older = row.status === "older_lot";
  const max = Math.max(row.measured, row.required);
  const box = (area, cls, label) => {
    const side = Math.max(18, Math.sqrt(area / max) * 170);
    return `<div class="sq"><svg class="box ${cls}" width="${side}" height="${side}" viewBox="0 0 ${side} ${side}" aria-hidden="true"><rect x="1" y="1" width="${side - 2}" height="${side - 2}"/></svg><span>${label}<br><b>${sqft(area)}</b></span></div>`;
  };
  const note = sizeNote(row);
  return `<div class="inset lot-squares" data-rule="${esc(row.rule)}"><div class="inset-title">Lot size, drawn to scale</div><div class="squares">${box(row.measured, "", "This lot")}${box(row.required, fails ? "over" : older ? "older" : "ghost", older ? "Smallest for a new lot" : "Smallest allowed")}</div>${note ? `<p class="sq-note">${note}</p>` : ""}</div>`;
}

/** One sentence under the lot-size squares comparing the lot with the smallest allowed. */
function sizeNote(row) {
  if (row.status === "fails") return `This lot has ${pct(row.measured / row.required)} of the land the zone requires.`;
  if (row.status === "older_lot") {
    return `This lot has ${pct(row.measured / row.required)} of the land the zone asks of a new lot. `
      + "Lots recorded before December 16, 2023 may still hold a house, a two-unit house or a townhouse.";
  }
  if (row.status !== "passes") return "";
  if (row.measured >= row.required) return "This lot is at least as big as the zone requires.";
  return "This lot is slightly smaller than the zone requires, but within the map's margin for measuring error.";
}

/** The lot's notes as a list. */
export function notesList(notes) {
  if (!notes || !notes.length) return "";
  return `<ul class="notes">${Array.from(new Set(notes)).map((n) => `<li>${esc(n)}</li>`).join("")}</ul>`;
}

const KIND_WORDS = { SUP: "special use permit", BZA: "variance", DSP: "site plan", DSUP: "site plan" };

/**
 * The city cases on file for the lot, as a heading and a list. Each case number links to
 * its first document, or to the city's search page when it has none. `ruleNames` maps a
 * rule id to the name the table shows, for the "Settles" line. Returns null with no cases.
 */
export function permitsList(permits, ruleNames = {}) {
  if (!permits || !permits.length) return null;
  const items = permits.map((p) => {
    const first = p.links && p.links[0];
    const href = first ? first.url : p.search_url;
    const number = href ? `<a href="${esc(href)}" target="_blank" rel="noopener">${esc(p.case)}</a>` : esc(p.case);
    const kind = KIND_WORDS[p.kind] || "city case";
    const detail = [kind, p.year, p.description].filter(Boolean).map((x) => esc(String(x))).join(" · ");
    const grants = (p.grants || []).map((id) => ruleNames[id] || id.replace(":", " "));
    const settles = grants.length ? `<div class="permit-settles">Settles: ${grants.map(esc).join(", ")}</div>` : "";
    return `<li><b>${number}</b> <span class="permit-detail">${detail}</span>${settles}</li>`;
  });
  return `<div class="permits"><div class="inset-title">Permits and approvals on file</div><ul>${items.join("")}</ul></div>`;
}
