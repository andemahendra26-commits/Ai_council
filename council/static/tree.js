/* The live council floor.

   Every protocol gets its own topology: the tiered hierarchy, a peer ring, a
   handoff chain, a blackboard hub, an event bus, and so on. Each node carries
   its vendor logo and streams its own thinking; output travels the edges as
   packets. As tiers finish they fade and the view climbs to the seats above,
   ending on the leader delivering the verdict. */
"use strict";

const VW = 1400, VH = 760;
const R = { leader: 44, minister: 34, member: 27 };

/* ---------- layout engines ------------------------------------------------ */
/* Each returns {place: [{seat, x, y, r, tier}], edges: [[fromId, toId]],
   extras: svg string, dynamic: bool}  — dynamic layouts grow edges at runtime. */

function ringPoints(count, cx, cy, rx, ry, from = -Math.PI / 2) {
  return Array.from({ length: count }, (_, i) => {
    const a = from + (i * 2 * Math.PI) / count;
    return { x: cx + Math.cos(a) * rx, y: cy + Math.sin(a) * ry };
  });
}
// 175px margin: half a node's 186px-wide label (93) plus its radius and a
// buffer, so a name never sits close enough to the edge to risk clipping.
function spread(count, y, x0 = 175, x1 = VW - 175) {
  const step = count > 1 ? (x1 - x0) / (count - 1) : 0;
  return Array.from({ length: count }, (_, i) => ({ x: count > 1 ? x0 + step * i : (x0 + x1) / 2, y }));
}

// A single row only has room for ~7 non-overlapping 186px-wide labels between
// the 175px margins. Once a tier has more seats than that, wrap it into a
// second staggered row instead of letting names run into each other.
const MAX_PER_ROW = 7;
function spreadWrapped(count, yTop, rowGap = 92, x0 = 175, x1 = VW - 175) {
  if (count <= MAX_PER_ROW) return spread(count, yTop, x0, x1).map((p) => ({ ...p, row: 0 }));
  const rows = Math.ceil(count / MAX_PER_ROW);
  const perRow = Math.ceil(count / rows);
  const out = [];
  for (let r = 0; r < rows; r++) {
    const n = Math.min(perRow, count - r * perRow);
    spread(n, yTop + r * rowGap, x0, x1).forEach((p) => out.push({ ...p, row: r }));
  }
  return out;
}

const LAYOUTS = {
  // Leader on top, ministers in the middle, members at the bottom.
  tiers(seats, chair) {
    const ministers = seats.filter((s) => s.rank === "minister");
    const members = seats.filter((s) => s.rank !== "minister");
    const place = [{ seat: chair, x: VW / 2, y: 80, r: R.leader, tier: "leader" }];
    spreadWrapped(ministers.length, 320, 84, 260, VW - 260).forEach((p, i) =>
      place.push({ seat: ministers[i], ...p, r: R.minister, tier: "minister" }));
    spreadWrapped(members.length, 566, 92).forEach((p, i) =>
      place.push({ seat: members[i], ...p, r: R.member, tier: "member" }));

    const parents = ministers.length ? ministers : [chair];
    const edges = members.map((s, i) => [s.id, parents[i % parents.length].id]);
    ministers.forEach((s) => edges.push([s.id, chair.id]));
    return { place, edges };
  },

  // Every seat answers at once, straight to the leader. An even row reads far
  // better than a ring here — a ring bunches nodes together at the poles.
  fan(seats, chair) {
    const place = [{ seat: chair, x: VW / 2, y: 96, r: R.leader, tier: "leader" }];
    spreadWrapped(seats.length, 420, 92).forEach((p, i) => {
      const s = seats[i];
      place.push({ seat: s, x: p.x, y: p.y, r: s.rank === "minister" ? R.minister : R.member,
                   tier: s.rank === "minister" ? "minister" : "member" });
    });
    return { place, edges: seats.map((s) => [s.id, chair.id]) };
  },

  // Same fan, plus every seat cross-examining every other.
  debate(seats, chair) {
    const base = LAYOUTS.fan(seats, chair);
    const edges = [...base.edges];
    for (let i = 0; i < seats.length; i++)
      for (let j = i + 1; j < seats.length; j++)
        if ((i + j) % 2 === 0) edges.push([seats[i].id, seats[j].id, "peer"]);
    return { place: base.place, edges };
  },

  // Peers talking directly, leader in the middle only to record consensus.
  ring(seats, chair) {
    const pts = ringPoints(seats.length, VW / 2, VH / 2 - 20, VW / 2 - 270, 220);
    const place = seats.map((s, i) => ({
      seat: s, x: pts[i].x, y: pts[i].y,
      r: s.rank === "minister" ? R.minister : R.member,
      tier: s.rank === "minister" ? "minister" : "member",
    }));
    place.push({ seat: chair, x: VW / 2, y: VH / 2 - 20, r: R.leader, tier: "leader" });
    const edges = [];
    seats.forEach((s, i) => edges.push([s.id, seats[(i + 1) % seats.length].id, "peer"]));
    seats.forEach((s) => edges.push([s.id, chair.id, "faint"]));
    return { place, edges };
  },

  // A ticket travelling seat to seat; edges are drawn as the baton moves.
  chain(seats, chair) {
    const perRow = Math.ceil(seats.length / 2) || 1;
    const place = [];
    seats.forEach((s, i) => {
      const rowIdx = Math.floor(i / perRow), col = i % perRow;
      const xs = spread(perRow, 0, 175, VW - 260);
      const x = rowIdx % 2 ? xs[perRow - 1 - col].x : xs[col].x;
      place.push({ seat: s, x, y: 200 + rowIdx * 230,
                   r: s.rank === "minister" ? R.minister : R.member,
                   tier: s.rank === "minister" ? "minister" : "member" });
    });
    place.push({ seat: chair, x: VW - 180, y: VH - 110, r: R.leader, tier: "leader" });
    return { place, edges: [], dynamic: true };
  },

  // Scattered swarm; the baton draws its own path.
  orbit(seats, chair) {
    const pts = ringPoints(seats.length, VW / 2, VH / 2 - 30, VW / 2 - 270, 230, -Math.PI / 2 + 0.4);
    const place = seats.map((s, i) => ({
      seat: s, x: pts[i].x, y: pts[i].y,
      r: s.rank === "minister" ? R.minister : R.member,
      tier: s.rank === "minister" ? "minister" : "member",
    }));
    place.push({ seat: chair, x: VW / 2, y: VH / 2 - 30, r: R.leader, tier: "leader" });
    return { place, edges: [], dynamic: true };
  },

  // One shared board in the middle; nobody addresses anybody.
  board(seats, chair) {
    const pts = ringPoints(seats.length, VW / 2, VH / 2 - 10, VW / 2 - 260, 240);
    const place = seats.map((s, i) => ({
      seat: s, x: pts[i].x, y: pts[i].y,
      r: s.rank === "minister" ? R.minister : R.member,
      tier: s.rank === "minister" ? "minister" : "member",
    }));
    place.push({ seat: chair, x: VW / 2, y: 74, r: R.leader, tier: "leader" });
    const bx = VW / 2 - 130, by = VH / 2 - 80;
    return {
      place,
      edges: seats.map((s) => [s.id, "__board__", "both"]),
      hub: { id: "__board__", x: VW / 2, y: VH / 2 - 10 },
      extras: `<rect class="sboard" x="${bx}" y="${by}" width="260" height="140" rx="3"/>
               <text class="sboardtx" x="${VW / 2}" y="${by + 26}" text-anchor="middle">BLACKBOARD</text>`,
    };
  },

  // A bus with handlers subscribed above and below it.
  bus(seats, chair) {
    const y = VH / 2 - 20;
    const half = Math.ceil(seats.length / 2);
    const place = [];
    const tierOf = (s) => (s.rank === "minister" ? "minister" : "member");
    const rOf = (s) => (s.rank === "minister" ? R.minister : R.member);
    spread(half, y - 175, 220, VW - 260).forEach((p, i) => {
      const s = seats[i];
      if (s) place.push({ seat: s, ...p, r: rOf(s), tier: tierOf(s) });
    });
    spread(seats.length - half, y + 175, 220, VW - 260).forEach((p, i) => {
      const s = seats[half + i];
      if (s) place.push({ seat: s, ...p, r: rOf(s), tier: tierOf(s) });
    });
    place.push({ seat: chair, x: 160, y, r: R.leader, tier: "leader" });
    return {
      place,
      edges: seats.map((s) => [s.id, "__bus__", "both"]),
      hub: { id: "__bus__", x: VW - 160, y },
      extras: `<line class="sbus" x1="220" y1="${y}" x2="${VW - 140}" y2="${y}"/>
               <text class="sboardtx" x="${VW - 160}" y="${y - 18}" text-anchor="middle">EVENT BUS</text>`,
    };
  },
};

const PATTERN_LAYOUT = {
  orchestration: "tiers", supervisor: "tiers", hierarchical: "tiers",
  fanout: "fan", debate: "debate", a2a: "ring",
  handoff: "chain", pipeline: "chain", swarm: "orbit",
  blackboard: "board", event_driven: "bus",
};

/* ---------- the stage ----------------------------------------------------- */

const Tree = {
  nodes: new Map(), edges: [], packets: [], hubs: new Map(),
  focus: 0, raf: null, chairId: null, dynamic: false, lastSpeaker: null, layout: "tiers",

  reset() {
    this.nodes.clear(); this.edges.length = 0; this.packets.length = 0; this.hubs.clear();
    this.focus = 0; this.chairId = null; this.lastSpeaker = null;
    if (this.raf) cancelAnimationFrame(this.raf);
    this.raf = null;
    $("#treeNodes").innerHTML = "";
    $("#treeEdges").innerHTML = "";
    $("#stage").hidden = true;
    $("#verdictPanel").hidden = true;
    $("#verdictBody").innerHTML = "";
  },

  build(seats, chair, patternId, patternName) {
    this.reset();
    $("#stage").hidden = false;
    this.chairId = chair.id;
    this.layout = PATTERN_LAYOUT[patternId] || "tiers";
    $("#stagePhase").textContent = patternName || patternId || "";

    const spec = LAYOUTS[this.layout](seats, chair);
    this.dynamic = !!spec.dynamic;
    if (spec.extras) $("#treeEdges").insertAdjacentHTML("beforeend", spec.extras);
    if (spec.hub) this.hubs.set(spec.hub.id, { x: spec.hub.x, y: spec.hub.y, r: 8 });

    spec.place.forEach((p) => this.addNode(p.seat, p.x, p.y, p.r, p.tier));
    (spec.edges || []).forEach(([a, b, kind]) => this.addEdge(a, b, kind));

    $("#stageHint").textContent = {
      tiers: "members report up to ministers, ministers to the leader",
      fan: "every seat answers at once, the leader merges",
      debate: "seats cross-examine each other, then the leader rules",
      ring: "seats message each other directly, no manager",
      chain: "the ticket moves seat to seat until it is resolved",
      orbit: "whoever holds the task picks who takes it next",
      board: "seats read and write one shared board",
      bus: "events dispatch to handlers, handlers emit more events",
    }[this.layout] || "";

    this.setScale();
    this.loop();
  },

  addNode(seat, x, y, r, tier) {
    const el = document.createElement("div");
    el.className = `tnode tier-${tier}`;
    el.style.cssText = `left:${x}px; top:${y}px; --seat:${seat.color}; --r:${r}px`;
    el.innerHTML = `
      <div class="halo"></div><div class="ring"></div>
      <div class="disc">${logoFor(seat, tier === "leader")}</div>
      <div class="tinfo">
        <div class="tmeta">
          <div class="tname">${esc(seat.name)}</div>
          <div class="trank">${esc(seat.label || tier)}</div>
        </div>
        <div class="tbubble"><span class="tstate"></span><span class="ttext"></span></div>
      </div>`;
    el.title = `${seat.name} — ${seat.model}`;
    el.onclick = () => {
      const card = document.querySelector(`[data-card^="${CSS.escape(seat.id)}:"]`);
      $("#logWrap").open = true;
      if (card) card.scrollIntoView({ behavior: "smooth", block: "center" });
    };
    $("#treeNodes").appendChild(el);
    this.nodes.set(seat.id, {
      seat, el, x, y, r, tier, state: "idle",
      bubble: el.querySelector(".tbubble"), text: el.querySelector(".ttext"),
      stateEl: el.querySelector(".tstate"), reason: "", wrote: 0, spawn: 0,
    });
  },

  point(id) {
    if (this.hubs.has(id)) return this.hubs.get(id);
    const n = this.nodes.get(id);
    return n ? { x: n.x, y: n.y, r: n.r } : null;
  },

  addEdge(fromId, toId, kind) {
    const a = this.point(fromId), b = this.point(toId);
    if (!a || !b || fromId === toId) return null;
    if (this.edges.some((e) => e.from === fromId && e.to === toId)) return null;
    const dx = b.x - a.x, dy = b.y - a.y;
    const dist = Math.hypot(dx, dy) || 1;
    const ux = dx / dist, uy = dy / dist;
    const sx = a.x + ux * a.r, sy = a.y + uy * a.r;
    const ex = b.x - ux * b.r, ey = b.y - uy * b.r;
    const bend = kind === "peer" ? 0.16 : 0.09;
    const cx = (sx + ex) / 2 - dy * bend, cy = (sy + ey) / 2 + dx * bend;
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", `M${sx} ${sy} Q${cx} ${cy} ${ex} ${ey}`);
    path.setAttribute("class", `tedge ${kind || ""}`);
    $("#treeEdges").appendChild(path);
    const edge = { from: fromId, to: toId, path, kind };
    this.edges.push(edge);
    return edge;
  },

  edgesFrom(id) { return this.edges.filter((e) => e.from === id); },

  /* ---- state ---- */
  setState(id, state) {
    const node = this.nodes.get(id);
    if (!node) return;
    node.state = state;
    node.el.dataset.state = state;
    node.stateEl.textContent =
      { thinking: "reasoning", writing: "reporting", done: "", failed: "failed" }[state] || "";
    if (state === "done") this.burst(id, 7);
    if (state === "writing") this.burst(id, 2);
  },

  // In dynamic layouts the topology is the story: draw the baton's path.
  activate(id) {
    if (this.dynamic && this.lastSpeaker && this.lastSpeaker !== id) {
      const edge = this.addEdge(this.lastSpeaker, id, "flowline");
      if (edge) this.spawnOn(edge, 5, this.nodes.get(this.lastSpeaker).seat.color);
    }
    if (id !== this.chairId) this.lastSpeaker = id;
    const node = this.nodes.get(id);
    if (node && node.tier === "member" && this.focus > 0) this.setFocus(0);
  },

  think(id, text) {
    const node = this.nodes.get(id);
    if (!node) return;
    node.reason += text;
    node.text.textContent = node.reason.slice(-150);
    node.bubble.classList.add("on");
  },

  write(id, text) {
    const node = this.nodes.get(id);
    if (!node) return;
    node.wrote += text.length;
    node.text.textContent = `${node.wrote.toLocaleString()} chars`;
    node.bubble.classList.add("on");
    if (node.wrote - node.spawn > 400) { node.spawn = node.wrote; this.burst(id, 1); }
  },

  burst(id, count) {
    const node = this.nodes.get(id);
    if (!node) return;
    const edges = this.edgesFrom(id);
    if (!edges.length) return;
    // Send up the hierarchy first; peer chatter gets a lighter trickle.
    const primary = edges.filter((e) => e.kind !== "peer" && e.kind !== "faint");
    (primary.length ? primary : edges).forEach((e) => this.spawnOn(e, count, node.seat.color));
  },

  spawnOn(edge, count, color) {
    const len = edge.path.getTotalLength();
    for (let i = 0; i < count; i++) {
      this.packets.push({
        path: edge.path, len, t: -i * 0.12,
        speed: 0.006 + Math.random() * 0.004, color, el: null,
      });
    }
  },

  loop() {
    const svg = $("#treeEdges");
    const step = () => {
      for (let i = this.packets.length - 1; i >= 0; i--) {
        const p = this.packets[i];
        p.t += p.speed;
        if (p.t < 0) continue;
        if (p.t > 1) { if (p.el) p.el.remove(); this.packets.splice(i, 1); continue; }
        if (!p.el) {
          p.el = document.createElementNS("http://www.w3.org/2000/svg", "circle");
          p.el.setAttribute("r", "4");
          p.el.setAttribute("class", "tpacket");
          p.el.setAttribute("fill", p.color);
          svg.appendChild(p.el);
        }
        const pt = p.path.getPointAtLength(p.t * p.len);
        p.el.setAttribute("cx", pt.x);
        p.el.setAttribute("cy", pt.y);
        p.el.setAttribute("opacity", String(Math.sin(p.t * Math.PI) * 0.9 + 0.1));
      }
      this.raf = requestAnimationFrame(step);
    };
    this.raf = requestAnimationFrame(step);
  },

  /* ---- staged focus ---- */
  tierNodes(tier) { return [...this.nodes.values()].filter((n) => n.tier === tier); },
  tierDone(tier) {
    const list = this.tierNodes(tier);
    return list.length > 0 && list.every((n) => n.state === "done" || n.state === "failed");
  },

  // Only the "tiers" layout gets a partial zoom once members report up to
  // ministers — a genuine mid-deliberation milestone there. The final zoom to
  // the leader is triggered deterministically when the verdict round starts
  // (see the "round_start" handler), not inferred from tier state here, since
  // several topologies (event bus, swarm, multi-wave debate) don't map onto
  // "member tier" / "minister tier" cleanly enough for that to be reliable.
  maybeAdvance() {
    if (this.layout === "tiers" && this.focus === 0 &&
        this.tierDone("member") && this.tierNodes("minister").length) {
      this.setFocus(1);
    }
  },

  setFocus(level) {
    if (level === this.focus) return;
    this.focus = level;
    const tree = $("#tree");
    tree.dataset.focus = String(level);
    this.setScale();
  },

  setScale() {
    const vp = $("#viewport").clientWidth || VW;
    const base = vp / VW;
    const tree = $("#tree"), view = $("#viewport");
    const leader = this.nodes.get(this.chairId);
    const ly = leader ? leader.y : 80;
    // Fitting the full width (focus 0) must scale from the top-left corner —
    // a centered origin leaves a gap on one side and clips the other, since
    // the unscaled tree is exactly `vp/base` wide, not float-centered in it.
    // Zooming in on the leader (focus 1/2) wants a centered origin instead,
    // so the leader (near the horizontal middle in every layout) stays put.
    if (this.focus === 0) {
      tree.style.transformOrigin = "0 0";
      tree.style.transform = `scale(${base})`;
      view.style.height = `${VH * base}px`;
    } else if (this.focus === 1) {
      tree.style.transformOrigin = "50% 0";
      const k = base * 1.4;
      tree.style.transform = `scale(${k}) translate(0px, ${-(ly - 120)}px)`;
      view.style.height = `${VH * base * 0.84}px`;
    } else {
      tree.style.transformOrigin = "50% 0";
      const k = base * 1.8;
      tree.style.transform = `scale(${k}) translate(0px, ${-(ly - 150)}px)`;
      view.style.height = `${VH * base * 0.7}px`;
    }
  },

  verdict(html) {
    $("#verdictPanel").hidden = false;
    $("#verdictBody").innerHTML = html;
  },
};

window.addEventListener("resize", () => { if (!$("#stage").hidden) Tree.setScale(); });
