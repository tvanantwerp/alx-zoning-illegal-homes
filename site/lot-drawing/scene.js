import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { fmt, showValue } from "./format.js";

/** Colors used when the page doesn't define its own CSS variables. */
const FALLBACK_COLORS = {
  paper: "#f7f3ec",
  ink: "#1f1b16",
  muted: "#6b6257",
  accent: "#bf3a1e",
  lot: "#fbf8f2",
  building: "#d6ccbc",
  shed: "#e9e2d6",
  street: "#e8e1d5",
};

/** How strongly a yard strip is tinted toward the accent color. */
const STRIP_TINT = 0.35;

/** Outbuildings with no recorded height are drawn this tall. */
const DEFAULT_HEIGHT = 12;

/** Reads the drawing's colors from CSS variables on `el`, falling back to the defaults. */
function palette(el) {
  const style = getComputedStyle(el);
  const colors = {};
  for (const [name, fallback] of Object.entries(FALLBACK_COLORS)) {
    colors[name] = new THREE.Color(style.getPropertyValue("--" + name).trim() || fallback);
  }
  return colors;
}

/** Every point of a polygon list, holes included. */
const pointsOf = (polys) => polys.flatMap((poly) => poly.flat());

/** The box around a list of points. */
function bounds(pts) {
  const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
  return { minX: Math.min(...xs), maxX: Math.max(...xs), minY: Math.min(...ys), maxY: Math.max(...ys) };
}

/** The middle of the box around a polygon list. */
function centerOf(polys) {
  const b = bounds(pointsOf(polys));
  return [(b.minX + b.maxX) / 2, (b.minY + b.maxY) / 2];
}

/** Whether a point falls inside a polygon list, counting holes as outside. */
function inside(pt, polys) {
  let hit = false;
  for (const ring of polys.flat()) {
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      const [xi, yi] = ring[i], [xj, yj] = ring[j];
      if ((yi > pt[1]) !== (yj > pt[1]) && pt[0] < ((xj - xi) * (pt[1] - yi)) / (yj - yi) + xi) hit = !hit;
    }
  }
  return hit;
}

/** The point halfway along a line, by length. */
function midpoint(line) {
  const lengths = line.slice(1).map((b, i) => Math.hypot(b[0] - line[i][0], b[1] - line[i][1]));
  let left = lengths.reduce((a, b) => a + b, 0) / 2;
  for (let i = 0; i < lengths.length; i++) {
    if (left <= lengths[i] && lengths[i] > 0) {
      const t = left / lengths[i], a = line[i], b = line[i + 1];
      return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
    }
    left -= lengths[i];
  }
  return line[0];
}

/**
 * The front lot line moved `offset` feet toward the street, piece by piece,
 * so a dimension line can follow a curved front instead of cutting across it.
 * `lines` is a list of lines; `lot` is the lot's polygon list, used to tell
 * which side of each piece faces the street. Returns the moved pieces, the
 * loose ends (with the direction across the line there) and the point
 * halfway along.
 */
function frontTrace(lines, offset, lot) {
  const segs = lines.flatMap((line) => line.slice(1).map((b, i) => [line[i], b]));
  const key = (p) => p[0].toFixed(1) + "," + p[1].toFixed(1);
  const starts = new Map(), stops = new Map();
  const pieces = segs.map(([a, b]) => {
    const dx = b[0] - a[0], dy = b[1] - a[1], len = Math.hypot(dx, dy) || 1;
    let n = [dy / len, -dx / len];
    const probe = [(a[0] + b[0]) / 2 + n[0] * 0.5, (a[1] + b[1]) / 2 + n[1] * 0.5];
    if (inside(probe, lot)) n = [-n[0], -n[1]];
    const piece = { a: [a[0] + n[0] * offset, a[1] + n[1] * offset], b: [b[0] + n[0] * offset, b[1] + n[1] * offset], n, len, from: a, to: b };
    starts.set(key(a), piece);
    stops.set(key(b), piece);
    return piece;
  });
  const ends = [];
  for (const piece of pieces) {
    if (!stops.has(key(piece.from))) ends.push({ p: piece.a, base: piece.from, n: piece.n });
    if (!starts.has(key(piece.to))) ends.push({ p: piece.b, base: piece.to, n: piece.n });
  }
  const total = pieces.reduce((sum, piece) => sum + piece.len, 0);
  let walked = 0, mid = null;
  for (const piece of pieces) {
    if (walked + piece.len >= total / 2) {
      const t = (total / 2 - walked) / piece.len;
      mid = { p: [piece.a[0] + (piece.b[0] - piece.a[0]) * t, piece.a[1] + (piece.b[1] - piece.a[1]) * t], n: piece.n };
      break;
    }
    walked += piece.len;
  }
  return { pieces, ends, mid };
}

/** The longest stretch of touching edges along each named street, so each street gets one label. */
function streetRuns(edges) {
  const longest = new Map();
  for (const run of touchingRuns(edges)) {
    run.length = run.line.slice(1).reduce((sum, b, i) => sum + Math.hypot(b[0] - run.line[i][0], b[1] - run.line[i][1]), 0);
    if (!longest.has(run.street) || longest.get(run.street).length < run.length) longest.set(run.street, run);
  }
  return [...longest.values()];
}

/** Joins touching street edges with the same name into runs. */
function touchingRuns(edges) {
  const same = (p, q) => Math.abs(p[0] - q[0]) < 0.05 && Math.abs(p[1] - q[1]) < 0.05;
  const runs = [];
  let last = null;
  for (const edge of edges) {
    if (edge.kind !== "street" || !edge.line.length) { last = null; continue; }
    if (last && last.street === edge.street && same(last.line.at(-1), edge.line[0])) {
      last.line.push(...edge.line.slice(1));
    } else {
      last = { street: edge.street, line: [...edge.line] };
      runs.push(last);
    }
  }
  const first = runs[0], end = runs.at(-1);
  if (runs.length > 1 && first.street === end.street && same(end.line.at(-1), first.line[0])) {
    first.line = end.line.concat(first.line.slice(1));
    runs.pop();
  }
  return runs;
}

/** "{measured} of {required} allowed", or the open space wording when the rule sets a minimum. */
function sizeLabel(row) {
  if (row.limit === "min") return `${row.name} ${showValue(row.measured, row.unit)} · needs ${showValue(row.required, row.unit)}`;
  const required = row.unit === "sq ft" ? fmt(row.required) : showValue(row.required, row.unit);
  return `${showValue(row.measured, row.unit)} of ${required} allowed`;
}

/** "{name} {measured} · {detail} {required}", with the required depth placed before any trailing ", …" note. */
function yardLabel(row) {
  const required = showValue(row.required, row.unit);
  const detail = row.detail || "";
  const comma = detail.indexOf(",");
  const rest = comma === -1 ? `${detail} ${required}` : `${detail.slice(0, comma)} ${required}${detail.slice(comma)}`;
  return `${row.name} ${showValue(row.measured, row.unit)} · ${rest.trim()}`;
}

/**
 * Draw a lot in 3D inside `container`. Returns controls for the pop-up.
 *
 * `lot` is a lot file; `results` is one of its result sets ({label, rules}).
 * Only failing rules are drawn. Labels are HTML elements with the classes
 * "tag", "tag fail" and "tag street", placed over the canvas; the page styles them.
 */
export function drawLot(container, lot, results) {
  const failing = ((results && results.rules) || []).filter((row) => row.status === "fails");
  const failingRule = (id) => failing.find((row) => row.rule === id);
  const C = palette(container);
  if (getComputedStyle(container).position === "static") container.style.position = "relative";

  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  } catch {
    const note = document.createElement("p");
    note.className = "drawing-error";
    note.textContent = "This browser couldn't draw the lot in 3D.";
    container.appendChild(note);
    return { highlight() {}, dispose() { note.remove(); } };
  }
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setSize(container.clientWidth || 1, container.clientHeight || 1);
  container.prepend(renderer.domElement);

  const scene = new THREE.Scene();
  const lotBox = bounds(pointsOf(lot.lot));
  /** A building's pieces, each with its own roof height. A building with no `parts` is one piece. */
  const piecesOf = (b) => b.parts || [{ outline: b.outline, height: b.height ?? DEFAULT_HEIGHT }];
  const heightOf = (b) => Math.max(...piecesOf(b).map((p) => p.height));
  const heightRow = failingRule("height");
  const limit = heightRow && heightRow.required ? heightRow.required : null;
  const maxH = Math.max(0, ...lot.buildings.map(heightOf), limit || 0);
  const lotW = lotBox.maxX - lotBox.minX, lotD = lotBox.maxY - lotBox.minY;
  const target = new THREE.Vector3((lotBox.minX + lotBox.maxX) / 2, maxH * 0.25, -(lotBox.minY + lotBox.maxY) / 2 + lotD * 0.08);
  // Far enough back that a ball around the lot and its tallest building fits in the view.
  const distance = Math.max(0.5 * Math.hypot(lotW, lotD, maxH * 2), 25) * 3.4;

  const camera = new THREE.PerspectiveCamera(32, (container.clientWidth || 1) / (container.clientHeight || 1), 1, distance * 20);
  camera.position.copy(target).addScaledVector(new THREE.Vector3(0.75, 0.85, 1.25).normalize(), distance);
  scene.add(new THREE.HemisphereLight(0xffffff, 0x8a8070, 0.95 * Math.PI));
  const sun = new THREE.DirectionalLight(0xffffff, 0.7 * Math.PI);
  sun.position.set(-1, 2, 1.2);
  scene.add(sun);

  /**
   * Parts tied to rules, for highlight(). A part is a label, or a 3D object
   * whose strength is its opacity, or, when `tinted`, how far its color
   * leans from the lot's color toward the accent.
   */
  const parts = [];
  const tags = [];
  const mark = (obj, rules, tinted = false) => {
    if (!tinted) obj.material.transparent = true;
    parts.push({ obj, rules, tinted, base: tinted ? STRIP_TINT : obj.material.opacity });
    scene.add(obj);
    return obj;
  };

  const v2 = ([x, y]) => new THREE.Vector2(x, y);
  const v3 = ([x, y], h = 0) => new THREE.Vector3(x, h, -y);
  const shapeOf = (poly) => {
    const shape = new THREE.Shape(poly[0].map(v2));
    for (const hole of poly.slice(1)) shape.holes.push(new THREE.Path(hole.map(v2)));
    return shape;
  };
  const flat = (polys, color, y, opacity = 1) => polys.map((poly) => {
    const geo = new THREE.ShapeGeometry(shapeOf(poly));
    geo.rotateX(-Math.PI / 2);
    const mat = new THREE.MeshBasicMaterial({ color, transparent: opacity < 1, opacity, side: THREE.DoubleSide, depthWrite: opacity === 1 });
    const mesh = new THREE.Mesh(geo, mat);
    mesh.position.y = y;
    return mesh;
  });
  // Lines get wider on big lots, which are drawn from farther away, so they stay visible.
  const lineScale = Math.max(1, distance / 250);
  const ribbon = (a, b, width, color, y) => {
    width *= lineScale;
    const dx = b[0] - a[0], dy = b[1] - a[1], len = Math.hypot(dx, dy) || 1;
    const nx = (-dy / len) * width / 2, ny = (dx / len) * width / 2;
    const pts = [[a[0] + nx, a[1] + ny], [b[0] + nx, b[1] + ny], [b[0] - nx, b[1] - ny], [a[0] - nx, a[1] - ny]];
    const geo = new THREE.BufferGeometry().setFromPoints([0, 1, 2, 0, 2, 3].map((i) => v3(pts[i], y)));
    return new THREE.Mesh(geo, new THREE.MeshBasicMaterial({ color, side: THREE.DoubleSide }));
  };
  const ribbons = (line, width, color, y) => line.slice(1).map((b, i) => ribbon(line[i], b, width, color, y));
  const tag = (pos, text, cls, rule) => {
    const div = document.createElement("div");
    div.className = "tag" + (cls ? " " + cls : "");
    div.textContent = text;
    Object.assign(div.style, { position: "absolute", left: "0", top: "0", pointerEvents: "none", whiteSpace: "nowrap" });
    container.appendChild(div);
    tags.push({ pos, div, size: null });
    if (rule) parts.push({ div, rules: [rule] });
  };

  // Ground, the front street and the lot.
  const ground = new THREE.Mesh(new THREE.CircleGeometry(distance * 4, 64), new THREE.MeshBasicMaterial({ color: C.paper }));
  ground.rotateX(-Math.PI / 2);
  ground.position.y = -0.2;
  scene.add(ground);
  const frontRow = ((results && results.rules) || []).find((row) => row.rule === "frontage");
  const frontPts = ((frontRow && frontRow.shapes && frontRow.shapes.line) || []).flat();
  if (lot.edges.some((e) => e.kind === "street")) {
    const frontY = frontPts.length ? Math.min(...frontPts.map((p) => p[1])) : lotBox.minY;
    const reach = distance * 2;
    const band = [[[lotBox.minX - reach, frontY - 1], [lotBox.maxX + reach, frontY - 1], [lotBox.maxX + reach, frontY - 26], [lotBox.minX - reach, frontY - 26]]];
    scene.add(...flat([band], C.street, -0.1));
  }
  scene.add(...flat(lot.lot, C.lot, 0));
  for (const edge of lot.edges) scene.add(...ribbons(edge.line, edge.kind === "street" ? 1.4 : 0.35, C.ink, 0.12));
  for (const run of streetRuns(lot.edges)) {
    if (!run.street) continue;
    const trace = frontTrace([run.line], 12, lot.lot);
    if (trace.mid) tag(v3(trace.mid.p), run.street, "street");
  }

  // Yards the home reaches into: the required strip, shaded, and the actual gap.
  for (const row of failing.filter((r) => r.rule.startsWith("yard:"))) {
    const shapes = row.shapes || {};
    // Strips are solid, tinted toward the accent, because a see-through strip that overlaps itself shades twice.
    if (shapes.strip) for (const mesh of flat(shapes.strip, C.lot.clone().lerp(C.accent, STRIP_TINT), 0.06)) mark(mesh, [row.rule], true);
    for (const line of shapes.gap || []) for (const mesh of ribbons(line, 0.6, C.accent, 0.2)) mark(mesh, [row.rule]);
    const at = shapes.gap && shapes.gap.length ? midpoint(shapes.gap[0]) : shapes.strip ? centerOf(shapes.strip) : null;
    if (at) tag(v3(at, 0.5), yardLabel(row), "fail", row.rule);
  }

  // Street frontage, as a dimension line just off the front lot line.
  const frontage = failingRule("frontage");
  if (frontage && frontage.shapes && frontage.shapes.line) {
    const trace = frontTrace(frontage.shapes.line, 5, lot.lot);
    for (const q of trace.pieces) mark(ribbon(q.a, q.b, 0.5, C.accent, 0.05), ["frontage"]);
    for (const e of trace.ends) mark(ribbon(e.base, [e.p[0] + e.n[0] * 1.5, e.p[1] + e.n[1] * 1.5], 0.35, C.accent, 0.05), ["frontage"]);
    if (trace.mid) {
      const p = [trace.mid.p[0] + trace.mid.n[0] * 5, trace.mid.p[1] + trace.mid.n[1] * 5];
      tag(v3(p), `${showValue(frontage.measured, frontage.unit)} of street frontage · needs ${showValue(frontage.required, frontage.unit)}`, "fail", "frontage");
    }
  }

  // Lot width, as a line across the lot where it is measured.
  const width = failingRule("width");
  if (width && width.shapes && width.shapes.line) {
    for (const line of width.shapes.line) for (const mesh of ribbons(line, 0.5, C.accent, 0.25)) mark(mesh, ["width"]);
    const line = width.shapes.line[0];
    const [a, b] = line[0][0] <= line.at(-1)[0] ? [line[0], line[1]] : [line.at(-1), line.at(-2)];
    const len = Math.hypot(b[0] - a[0], b[1] - a[1]) || 1;
    const at = [a[0] - ((b[0] - a[0]) / len) * 6, a[1] - ((b[1] - a[1]) / len) * 6];
    const text = `${showValue(width.measured, width.unit)} wide · needs ${showValue(width.required, width.unit)}` + (width.detail ? `, ${width.detail}` : "");
    tag(v3(at, 0.5), text, "fail", "width");
  }

  // Buildings. Homes named by a failing rule are red; anything over a failing height limit is solid red above it.
  const rulesFor = new Map();
  for (const row of failing) for (const i of row.buildings || []) rulesFor.set(i, [...(rulesFor.get(i) || []), row.rule]);
  const softRed = C.accent.clone().lerp(C.paper, 0.5);
  const extrude = (poly, from, to, color, rules) => {
    const geo = new THREE.ExtrudeGeometry(shapeOf(poly), { depth: to - from, bevelEnabled: false });
    geo.rotateX(-Math.PI / 2);
    const mesh = new THREE.Mesh(geo, new THREE.MeshLambertMaterial({ color }));
    mesh.position.y = from;
    scene.add(mesh);
    const lines = new THREE.LineSegments(new THREE.EdgesGeometry(geo),
      new THREE.LineBasicMaterial({ color: rules ? C.accent : C.ink, transparent: true, opacity: rules ? 1 : 0.55 }));
    lines.position.y = from;
    if (rules) mark(lines, rules);
    else scene.add(lines);
  };
  lot.buildings.forEach((b, i) => {
    const rules = rulesFor.get(i) || null;
    const base = !b.is_home ? C.shed : rules ? softRed : C.building;
    for (const { outline, height: h } of piecesOf(b)) {
      for (const poly of outline) {
        if (limit && h > limit) {
          extrude(poly, 0, limit, base, rules);
          extrude(poly, limit, h, C.accent, rules || ["height"]);
        } else {
          extrude(poly, 0, h, base, rules);
        }
      }
    }
  });

  /** Where a building rule's label goes: over the listed buildings, or the middle of the lot. */
  const listed = (row) => (row.buildings || []).map((i) => lot.buildings[i]).filter(Boolean);
  const spotFor = (row) => {
    const bs = listed(row);
    if (!bs.length) return { at: centerOf(lot.lot), top: 0 };
    return { at: centerOf(bs.flatMap((b) => b.outline)), top: Math.max(...bs.map(heightOf)) };
  };
  const floorArea = failingRule("floor_area");
  if (floorArea) {
    const { at, top } = spotFor(floorArea);
    tag(v3(at, top * 0.45), sizeLabel(floorArea), "fail", "floor_area");
  }
  for (const row of failing.filter((r) => r.rule === "coverage" || r.rule === "open_space")) {
    const { at } = spotFor(row);
    tag(v3([at[0], at[1] - 6], 1), sizeLabel(row), "fail", row.rule);
  }

  // The height limit as a see-through ceiling over the lot, only when the height rule fails.
  if (limit) {
    for (const mesh of flat(lot.lot, C.accent, limit, 0.12)) mark(mesh, ["height"]);
    const ring = lot.lot[0][0];
    const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints(ring.concat([ring[0]]).map((p) => v3(p, limit))),
      new THREE.LineDashedMaterial({ color: C.accent, dashSize: 2, gapSize: 1.2 }));
    line.computeLineDistances();
    mark(line, ["height"]);
    const corner = ring.reduce((best, p) => (p[0] + p[1] > best[0] + best[1] ? p : best));
    tag(v3(corner, limit), `${showValue(limit, heightRow.unit)} height limit`, "fail", "height");
    const { at, top } = spotFor(heightRow);
    // When the roof is pitched, the measured height sits below the drawn peak, so the label names both.
    const peak = heightRow.detail ? ` · ${heightRow.detail}` : "";
    tag(v3(at, top + 4), `${showValue(heightRow.measured, heightRow.unit)} tall${peak}`, "fail", "height");
  }

  const controls = new OrbitControls(camera, renderer.domElement);
  controls.target.copy(target);
  controls.enableDamping = true;
  controls.maxPolarAngle = Math.PI / 2 - 0.08;
  controls.minDistance = distance * 0.3;
  controls.maxDistance = distance * 3;
  controls.autoRotate = !matchMedia("(prefers-reduced-motion: reduce)").matches;
  controls.autoRotateSpeed = 0.6;
  controls.addEventListener("start", () => { controls.autoRotate = false; });

  /** Puts each label over its 3D point, nudging labels down so they don't cover one another. */
  const placeTags = () => {
    const w = container.clientWidth, h = container.clientHeight;
    const projected = new THREE.Vector3();
    const shown = [];
    for (const t of tags) {
      projected.copy(t.pos).project(camera);
      const visible = projected.z < 1;
      t.div.style.display = visible ? "" : "none";
      if (!visible) continue;
      if (!t.size || !t.size.w) t.size = { w: t.div.offsetWidth, h: t.div.offsetHeight };
      shown.push({ t, x: ((projected.x + 1) / 2) * w, y: ((1 - projected.y) / 2) * h });
    }
    shown.sort((a, b) => a.y - b.y);
    const placed = [];
    for (const s of shown) {
      const { w: sw, h: sh } = s.t.size;
      s.x = Math.min(Math.max(s.x, sw / 2 + 4), w - sw / 2 - 4);
      s.y = Math.min(Math.max(s.y, sh / 2 + 4), h - sh / 2 - 4);
      for (let tries = 0; tries < 8; tries++) {
        const hit = placed.find((p) => Math.abs(p.x - s.x) < (p.w + sw) / 2 && Math.abs(p.y - s.y) < (p.h + sh) / 2);
        if (!hit) break;
        s.y = hit.y + (hit.h + sh) / 2 + 2;
      }
      placed.push({ x: s.x, y: s.y, w: sw, h: sh });
      s.t.div.style.transform = `translate(${s.x}px, ${s.y}px) translate(-50%, -50%)`;
    }
  };

  let frame = 0;
  const loop = () => {
    controls.update();
    renderer.render(scene, camera);
    placeTags();
    frame = requestAnimationFrame(loop);
  };
  loop();

  const observer = new ResizeObserver(() => {
    const w = container.clientWidth, h = container.clientHeight;
    if (!w || !h) return;
    renderer.setSize(w, h);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  });
  observer.observe(container);

  let disposed = false;
  return {
    /** Brightens the parts drawn for these rule ids and dims the rest. An empty list, or ids with nothing drawn, resets. */
    highlight(ids) {
      const want = new Set(ids || []);
      const active = parts.some((p) => p.rules.some((r) => want.has(r)));
      for (const p of parts) {
        const on = p.rules.some((r) => want.has(r));
        if (p.div) {
          p.div.style.opacity = !active || on ? "" : "0.15";
          p.div.classList.toggle("hl", active && on);
        } else {
          const level = !active ? p.base : on ? Math.min(1, p.base * 2) : p.base * 0.15;
          if (p.tinted) p.obj.material.color.copy(C.lot).lerp(C.accent, level);
          else p.obj.material.opacity = level;
        }
      }
    },
    /** Stops drawing and frees the renderer, every geometry and material, the labels and the resize watcher. */
    dispose() {
      if (disposed) return;
      disposed = true;
      cancelAnimationFrame(frame);
      observer.disconnect();
      controls.dispose();
      scene.traverse((obj) => {
        if (obj.geometry) obj.geometry.dispose();
        for (const mat of [].concat(obj.material || [])) mat.dispose();
      });
      renderer.dispose();
      renderer.forceContextLoss();
      renderer.domElement.remove();
      for (const t of tags) t.div.remove();
    },
  };
}
