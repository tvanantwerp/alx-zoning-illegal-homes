import { esc } from "./format.js";
import { chooseResults, rulesTable, lotSquares, notesList } from "./table.js";
const LOAD_ERROR = "The drawing for this lot couldn't be loaded. Try reloading the page.";
const NO_DRAWING = "The 3D drawing couldn't be shown here, but the rule results below are complete.";
const CAPTION = "Measured from the city's map data, not a survey. Drag to turn it.";

let sceneModule = null;

/**
 * Loads the 3D drawing code, and Three.js with it, the first time a lot is opened.
 * Loading it late keeps the map from waiting on Three.js. A failed load is
 * forgotten so the next lot tries again.
 */
function loadScene() {
  sceneModule ??= import("./scene.js").catch((error) => {
    sceneModule = null;
    throw error;
  });
  return sceneModule;
}

/**
 * Wire up the pop-up. `isOrdinary()` reads the shared switch; `setOrdinary(bool)` changes it everywhere.
 *
 * Expects a `<dialog id="lot-drawing">` on the page holding `.ld-title`, `.ld-meta`,
 * `.ld-switch` (a label around a checkbox), `.ld-close` and `.ld-body`.
 * Closing the pop-up hands focus to the element passed as `returnFocus` when it
 * was opened, or else to the map's canvas.
 * Returns `{ open(properties, { returnFocus }), refresh(), close() }`.
 */
export function setUpLotDrawing({ isOrdinary, setOrdinary }) {
  const dialog = document.getElementById("lot-drawing");
  const title = dialog.querySelector(".ld-title");
  const meta = dialog.querySelector(".ld-meta");
  const switchLabel = dialog.querySelector(".ld-switch");
  const switchBox = switchLabel.querySelector("input");
  const body = dialog.querySelector(".ld-body");
  const tips = setUpTips(dialog);

  let latest = 0;
  let lot = null;
  let view = null;
  let returnFocusTo = null;

  const clearDrawing = () => {
    if (view) view.dispose();
    view = null;
  };

  /** Swaps the drawing area for a plain sentence, for when the 3D drawing can't be shown. */
  const showNoDrawing = (holder) => {
    const note = document.createElement("p");
    note.className = "drawing-error";
    note.textContent = NO_DRAWING;
    holder.replaceChildren(note);
    const caption = holder.closest("figure")?.querySelector("figcaption");
    if (caption) caption.hidden = true;
  };

  /** Draws the lot in 3D once the drawing code has loaded, unless the pop-up has moved on by then. */
  const drawScene = async (holder, results, mine) => {
    let drawLot;
    try {
      ({ drawLot } = await loadScene());
    } catch {
      if (mine === latest) showNoDrawing(holder);
      return;
    }
    if (mine !== latest) return;
    try {
      view = drawLot(holder, lot, results);
    } catch {
      view = null;
      showNoDrawing(holder);
    }
  };

  /** Fills the header and body for the loaded lot under the current switch, and draws it. */
  const render = () => {
    const mine = ++latest;
    clearDrawing();
    tips.hide();
    const ordinary = isOrdinary();
    const { main, extra } = chooseResults(lot, ordinary);
    const broken = main.rules.filter((row) => row.status === "fails").length;
    const verdict = broken ? `Breaks ${broken} rule${broken === 1 ? "" : "s"}` : "Passes every rule the map checks";
    title.textContent = lot.address || "No address on record";
    meta.textContent = [lot.zone_label, lot.home_type, verdict].filter(Boolean).join(" · ");
    switchLabel.hidden = !(lot.district && lot.ordinary);
    switchBox.checked = ordinary;

    const sizeRow = main.rules.find((row) => row.rule === "lot_area");
    const squares = sizeRow ? lotSquares(sizeRow) : "";
    const notes = ordinary && lot.ordinary_notes && lot.ordinary_notes.length ? lot.ordinary_notes : lot.notes;
    body.innerHTML =
      `<div class="ld-top${squares ? " with-squares" : ""}">` +
      `<figure class="ld-figure"><div class="ld-three"></div><figcaption>${esc(CAPTION)}</figcaption></figure>` +
      squares +
      `</div>` +
      `<div class="ld-table${extra ? " has-extra" : ""}">${rulesTable(main, extra)}</div>` +
      notesList(notes);

    const square = body.querySelector(".lot-squares");
    const table = body.querySelector("table.report");
    const show = (rule) => {
      if (view) view.highlight(rule ? [rule] : []);
      if (square) square.classList.toggle("hl", rule === "lot_area");
    };
    for (const row of table.querySelectorAll("tr[data-rule]")) {
      row.addEventListener("mouseenter", () => show(row.dataset.rule));
      row.addEventListener("focusin", () => show(row.dataset.rule));
    }
    table.addEventListener("mouseleave", () => show(null));
    drawScene(body.querySelector(".ld-three"), main, mine);
  };

  /** Shows the pop-up for a lot on the map. Lots without an id weren't checked, so there is nothing to draw. */
  const open = async (properties, { returnFocus = null } = {}) => {
    if (!properties || properties.id == null) return;
    returnFocusTo = returnFocus;
    const mine = ++latest;
    clearDrawing();
    tips.hide();
    lot = null;
    title.textContent = properties.address || "No address on record";
    meta.textContent = "";
    switchLabel.hidden = true;
    body.innerHTML = `<p class="ld-status">Loading…</p>`;
    body.scrollTop = 0;
    if (!dialog.open) dialog.showModal();

    let data;
    try {
      const response = await fetch(`lots/${encodeURIComponent(properties.id)}.json`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      data = await response.json();
    } catch {
      if (mine === latest) body.innerHTML = `<p class="ld-status">${esc(LOAD_ERROR)}</p>`;
      return;
    }
    if (mine !== latest) return;
    lot = data;
    render();
  };

  /** Redraws the open lot under the current switch, keeping the scroll position. */
  const refresh = () => {
    if (!lot || !dialog.open) return;
    const scroll = body.scrollTop;
    render();
    body.scrollTop = scroll;
  };

  const close = () => {
    if (dialog.open) dialog.close();
  };

  switchBox.addEventListener("change", () => setOrdinary(switchBox.checked));
  dialog.querySelector(".ld-close").addEventListener("click", close);

  // A drag that starts on the drawing and ends over the backdrop also "clicks" the dialog,
  // so only a press that began on the backdrop closes it.
  let pressedBackdrop = false;
  dialog.addEventListener("pointerdown", (event) => { pressedBackdrop = event.target === dialog; });
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog && pressedBackdrop) close();
  });

  dialog.addEventListener("close", () => {
    // The close event arrives a moment after closing, so a lot opened right away may already be showing.
    if (dialog.open) return;
    latest++;
    clearDrawing();
    tips.hide();
    lot = null;
    body.innerHTML = "";
    const target = returnFocusTo?.isConnected ? returnFocusTo : document.querySelector(".maplibregl-canvas");
    returnFocusTo = null;
    if (target) target.focus();
  });

  return { open, refresh, close };
}

/**
 * Hover and focus tips for `.explain` elements inside `root`. One floating box,
 * placed under the element, or above it when there is no room below.
 * The box lives inside `root` so it shows above a modal dialog.
 */
function setUpTips(root) {
  const tipbox = document.createElement("div");
  tipbox.className = "tipbox";
  tipbox.setAttribute("role", "tooltip");
  tipbox.hidden = true;
  root.appendChild(tipbox);

  const showTip = (el) => {
    tipbox.textContent = el.dataset.tip;
    tipbox.hidden = false;
    const r = el.getBoundingClientRect(), box = tipbox.getBoundingClientRect();
    const left = Math.min(Math.max(16, r.left), window.innerWidth - box.width - 16);
    const below = r.bottom + 8 + box.height < window.innerHeight;
    tipbox.style.left = left + "px";
    tipbox.style.top = (below ? r.bottom + 8 : r.top - box.height - 8) + "px";
  };
  const hideTip = () => { tipbox.hidden = true; };

  for (const type of ["mouseover", "focusin"]) {
    root.addEventListener(type, (e) => { const el = e.target.closest?.(".explain"); if (el) showTip(el); });
  }
  for (const type of ["mouseout", "focusout"]) {
    root.addEventListener(type, (e) => { if (e.target.closest?.(".explain")) hideTip(); });
  }
  root.addEventListener("scroll", hideTip, { capture: true, passive: true });
  return { hide: hideTip };
}
