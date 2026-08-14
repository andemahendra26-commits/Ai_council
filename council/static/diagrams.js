/* Miniature topology diagrams — one per coordination protocol.
   Drawn in a 200x96 space; `n()` is a node, `e()` an edge, `a()` an arrowhead. */
"use strict";

const DIA_W = 200, DIA_H = 96;

function n(x, y, r, cls) {
  return `<circle class="dn ${cls || ""}" cx="${x}" cy="${y}" r="${r || 7}"/>`;
}
function e(x1, y1, x2, y2, cls) {
  return `<line class="de ${cls || ""}" x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}"/>`;
}
function curve(x1, y1, x2, y2, bend, cls) {
  const mx = (x1 + x2) / 2, my = (y1 + y2) / 2 - (bend || 18);
  return `<path class="de ${cls || ""}" d="M${x1} ${y1} Q${mx} ${my} ${x2} ${y2}"/>`;
}
function row(count, y, r, cls, x0, x1) {
  const a = x0 === undefined ? 26 : x0, b = x1 === undefined ? DIA_W - 26 : x1;
  const step = count > 1 ? (b - a) / (count - 1) : 0;
  return Array.from({ length: count }, (_, i) => ({ x: a + step * i, y }))
    .map((p) => ({ ...p, svg: n(p.x, p.y, r, cls) }));
}

/* Each entry returns the inner SVG for one protocol. */
const DIAGRAMS = {
  orchestration() {
    const top = { x: 100, y: 20 };
    const kids = row(4, 74, 7);
    return kids.map((k) => e(top.x, top.y + 8, k.x, k.y - 8, "up")).join("")
      + kids.map((k) => k.svg).join("")
      + n(top.x, top.y, 10, "lead");
  },
  a2a() {
    const p = [{ x: 45, y: 26 }, { x: 155, y: 26 }, { x: 155, y: 72 }, { x: 45, y: 72 }];
    let s = "";
    for (let i = 0; i < p.length; i++)
      for (let j = i + 1; j < p.length; j++) s += e(p[i].x, p[i].y, p[j].x, p[j].y, "thin");
    return s + p.map((q) => n(q.x, q.y, 8)).join("");
  },
  handoff() {
    const p = row(4, 48, 8, "", 30, 170);
    return p.slice(0, -1).map((q, i) => e(q.x + 9, q.y, p[i + 1].x - 9, q.y, "flow")).join("")
      + p.map((q, i) => n(q.x, q.y, 8, i === 2 ? "hot" : "")).join("");
  },
  pipeline() {
    const p = row(4, 48, 8, "", 30, 170);
    return p.slice(0, -1).map((q, i) => e(q.x + 9, q.y, p[i + 1].x - 9, q.y, "flow")).join("")
      + p.map((q) => q.svg).join("");
  },
  fanout() {
    const kids = row(4, 26, 7);
    const sink = { x: 100, y: 76 };
    return kids.map((k) => e(k.x, k.y + 8, sink.x, sink.y - 10, "down")).join("")
      + kids.map((k) => k.svg).join("") + n(sink.x, sink.y, 10, "lead");
  },
  supervisor() {
    const top = { x: 100, y: 22 };
    const kids = row(3, 74, 7);
    return kids.map((k) => e(top.x, top.y + 9, k.x, k.y - 8, "both")).join("")
      + kids.map((k) => k.svg).join("") + n(top.x, top.y, 10, "lead");
  },
  debate() {
    const p = row(4, 30, 7, "", 34, 166);
    let s = "";
    for (let i = 0; i < p.length; i++)
      for (let j = i + 1; j < p.length; j++) s += curve(p[i].x, p[i].y, p[j].x, p[j].y, 13, "thin");
    const sink = { x: 100, y: 78 };
    return s + p.map((q) => e(q.x, q.y + 8, sink.x, sink.y - 10, "down thin")).join("")
      + p.map((q) => q.svg).join("") + n(sink.x, sink.y, 10, "lead");
  },
  hierarchical() {
    const top = { x: 100, y: 16 };
    const mids = row(2, 48, 8, "min", 62, 138);
    const kids = row(4, 82, 6, "", 30, 170);
    let s = mids.map((m) => e(top.x, top.y + 9, m.x, m.y - 9, "up")).join("");
    kids.forEach((k, i) => { const m = mids[i < 2 ? 0 : 1]; s += e(m.x, m.y + 9, k.x, k.y - 7, "up"); });
    return s + kids.map((k) => k.svg).join("") + mids.map((m) => m.svg).join("")
      + n(top.x, top.y, 10, "lead");
  },
  swarm() {
    const p = [{ x: 38, y: 62 }, { x: 82, y: 26 }, { x: 128, y: 66 }, { x: 168, y: 32 }];
    let s = "";
    for (let i = 0; i < p.length - 1; i++)
      s += curve(p[i].x, p[i].y, p[i + 1].x, p[i + 1].y, i % 2 ? -20 : 20, "flow");
    return s + p.map((q, i) => n(q.x, q.y, 8, i === 3 ? "hot" : "")).join("");
  },
  blackboard() {
    const board = `<rect class="board" x="66" y="34" width="68" height="28" rx="2"/>`;
    const p = [{ x: 26, y: 22 }, { x: 174, y: 22 }, { x: 26, y: 74 }, { x: 174, y: 74 }];
    return p.map((q) => e(q.x, q.y, 100, 48, "both thin")).join("") + board
      + p.map((q) => n(q.x, q.y, 7)).join("");
  },
  event_driven() {
    const bus = `<line class="bus" x1="18" y1="48" x2="182" y2="48"/>`;
    const up = row(3, 20, 6, "", 46, 154);
    const dn = row(3, 76, 6, "", 32, 168);
    return bus
      + up.map((q) => e(q.x, q.y + 7, q.x, 44, "both thin")).join("")
      + dn.map((q) => e(q.x, q.y - 7, q.x, 52, "both thin")).join("")
      + up.map((q) => q.svg).join("") + dn.map((q) => q.svg).join("");
  },
};

function diagramFor(id) {
  const draw = DIAGRAMS[id];
  if (!draw) return "";
  return `<svg class="dia" viewBox="0 0 ${DIA_W} ${DIA_H}" preserveAspectRatio="xMidYMid meet">${draw()}</svg>`;
}
