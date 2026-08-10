// ai-report arch-flow v1 —— 只读节点编排图（分层流程 + 判断器 + 抽屉详情）。
// 契约：<div class="arch-flow"> 内含 <script type="application/json"> 数据，或 data-graph 属性。
// 布局：节点带 layer → 行布局（层即行）；无 layer 时留待接 dagre 自动布局（ponytail: 暂无此场景，不引依赖）。
// 渲染：SVG 画边，HTML 画节点；视觉 token 对齐 book-style.css。
(function () {
  "use strict";

  var W = 1000, BAND = 112, TOP = 26;
  var NODE_ZONE = [150, 880];          // 节点可用横向范围
  var CORRIDOR = { L: [54, 34], R: [912, 932, 952] }; // side 边走线走廊（按车道分配）
  // 功能三色：计算/流转=蓝，判断器=朱砂，存储/入口=灰（数据可用 color 覆盖）
  var KIND_COLOR = { def: "#0C4A6E", judge: "#A63A2E", store: "#6E7278", entry: "#6E7278" };

  function ioRow(k, tag, text, ex) {
    return '<div class="af-io"><span class="af-io-k ' + k + '">' + tag + "</span><div>" +
      "<code>" + esc(text) + "</code>" +
      (ex ? "<details><summary>example</summary><pre>" + esc(ex) + "</pre></details>" : "") +
      "</div></div>";
  }

  // ---------- 小工具 ----------
  function el(tag, cls, parent) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (parent) parent.appendChild(n);
    return n;
  }
  function svg(tag, attrs, parent) {
    var n = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (var k in attrs) n.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(n);
    return n;
  }
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }

  // 圆角正交折线：pts = [[x,y],...]，角点用二次曲线切圆角
  function orthPath(pts, r) {
    r = r == null ? 12 : r;
    var d = "M " + pts[0][0] + " " + pts[0][1];
    for (var i = 1; i < pts.length - 1; i++) {
      var p = pts[i - 1], c = pts[i], nx = pts[i + 1];
      var d1x = Math.sign(c[0] - p[0]), d1y = Math.sign(c[1] - p[1]);
      var d2x = Math.sign(nx[0] - c[0]), d2y = Math.sign(nx[1] - c[1]);
      var l1 = Math.abs(c[0] - p[0]) + Math.abs(c[1] - p[1]);
      var l2 = Math.abs(nx[0] - c[0]) + Math.abs(nx[1] - c[1]);
      var rr = Math.min(r, l1 / 2, l2 / 2);
      d += " L " + (c[0] - d1x * rr) + " " + (c[1] - d1y * rr) +
           " Q " + c[0] + " " + c[1] +
           " " + (c[0] + d2x * rr) + " " + (c[1] + d2y * rr);
    }
    var e = pts[pts.length - 1];
    return d + " L " + e[0] + " " + e[1];
  }

  // ---------- 布局：layer 决定行，行内均布 ----------
  function layout(data) {
    var rows = {};
    data.nodes.forEach(function (n) { (rows[n.layer] = rows[n.layer] || []).push(n); });
    var maxLayer = Math.max.apply(null, data.nodes.map(function (n) { return n.layer; }));
    var pos = {};
    Object.keys(rows).forEach(function (L) {
      var row = rows[L], cy = TOP + Number(L) * BAND + BAND / 2;
      var centers = row.length === 1
        ? [(NODE_ZONE[0] + NODE_ZONE[1]) / 2]
        : row.map(function (_, i) {
            return NODE_ZONE[0] + (NODE_ZONE[1] - NODE_ZONE[0]) * ((i + 1) / (row.length + 1));
          });
      row.forEach(function (n, i) {
        var judge = n.kind === "judge";
        var w = judge ? 216 : (row.length === 1 ? 400 : 306);
        var h = judge ? 92 : (n.sub ? 60 : 44);
        pos[n.id] = { x: centers[i], y: cy, w: w, h: h, node: n, judge: judge };
      });
    });
    return { pos: pos, height: TOP + (maxLayer + 1) * BAND + 30, maxLayer: maxLayer };
  }

  // ---------- 边路由 ----------
  function edgePath(e, s, t, laneX) {
    var down = t.y > s.y, dir = down ? 1 : -1;
    var dx = e.dx || 0;
    var sy = s.y + dir * s.h / 2, ty = t.y - dir * t.h / 2;
    if (e.side && laneX != null) {
      // 走廊边：源节点侧面出 → 走廊垂直走 → 目标节点侧面入
      var sEdge = e.side === "R" ? s.x + s.w / 2 : s.x - s.w / 2;
      var tEdge = e.side === "R" ? t.x + t.w / 2 : t.x - t.w / 2;
      return {
        d: orthPath([[sEdge, s.y], [laneX, s.y], [laneX, t.y], [tEdge, t.y]]),
        lx: laneX + (e.side === "R" ? -8 : 8),
        ly: (s.y + t.y) / 2,
        anchor: e.side === "R" ? "end" : "start"
      };
    }
    var sx = s.x + dx, tx = t.x + dx + (down ? 0 : 30), my = (sy + ty) / 2; // 上行边锚点右移，避免与下行箭头重叠
    var labelLeft = dx < 0;
    // 上行边标签贴近源节点，避开中途的节点图形
    var lx = down ? (sx + tx) / 2 + (labelLeft ? -8 : 8) : sx + 10;
    var ly = down ? my - 5 : sy - 10;
    return {
      d: "M " + sx + " " + sy + " C " + sx + " " + my + ", " + tx + " " + my + ", " + tx + " " + ty,
      lx: lx,
      ly: ly,
      anchor: labelLeft ? "end" : "start"
    };
  }

  // ---------- 渲染 ----------
  function render(box, data) {
    var L = layout(data);
    var pos = L.pos;
    var types = data.edgeTypes || {};
    var canvas = el("div", "af-canvas", box);
    canvas.style.width = W + "px";
    canvas.style.height = L.height + "px";

    // 层色带 + 层标签
    for (var i = 0; i <= L.maxLayer; i++) {
      var band = el("div", "af-band" + (i % 2 ? " af-band-alt" : ""), canvas);
      band.style.top = TOP + i * BAND + "px";
      band.style.height = BAND + "px";
      if (data.layers && data.layers[i]) {
        var lab = el("span", "af-band-label", band);
        lab.textContent = String(i + 1).padStart(2, "0") + " · " + data.layers[i];
      }
    }

    // 边层（SVG）
    var s = svg("svg", { width: W, height: L.height, viewBox: "0 0 " + W + " " + L.height }, canvas);
    s.classList.add("af-edges");
    var defs = svg("defs", {}, s);
    Object.keys(types).forEach(function (k) {
      var m = svg("marker", {
        id: "af-arr-" + k, viewBox: "0 0 8 8", refX: 7, refY: 4,
        markerWidth: 7, markerHeight: 7, orient: "auto"
      }, defs);
      svg("path", { d: "M0,0 L8,4 L0,8 z", fill: types[k].color }, m);
    });

    var lanes = { L: 0, R: 0 };
    var edgeEls = [];
    (data.edges || []).forEach(function (e) {
      var sP = pos[e.from], tP = pos[e.to];
      if (!sP || !tP) return;
      var laneX = e.side ? CORRIDOR[e.side][Math.min(lanes[e.side]++, CORRIDOR[e.side].length - 1)] : null;
      var r = edgePath(e, sP, tP, laneX);
      var t = types[e.type] || { color: "#6E7278" };
      var g = svg("g", { class: "af-edge", "data-from": e.from, "data-to": e.to }, s);
      var attrs = {
        d: r.d, fill: "none", stroke: t.color, "stroke-width": 1.7,
        "marker-end": "url(#af-arr-" + (types[e.type] ? e.type : "") + ")"
      };
      if (t.dash) attrs["stroke-dasharray"] = t.dash;
      if (!types[e.type]) attrs["marker-end"] = "";
      svg("path", attrs, g);
      if (e.label) {
        var txt = svg("text", {
          x: r.lx, y: r.ly, "text-anchor": r.anchor, class: "af-edge-label"
        }, g);
        txt.textContent = e.label;
        txt.style.fill = t.color;
        var bb = txt.getBBox(); // 标签底色矩形，遮住穿过的走廊线
        var bg = svg("rect", {
          x: bb.x - 4, y: bb.y - 2.5, width: bb.width + 8, height: bb.height + 5,
          rx: 3, class: "af-label-bg"
        }, g);
        g.insertBefore(bg, txt);
      }
      edgeEls.push(g);
    });

    // 节点层（HTML）
    var nodeEls = {};
    data.nodes.forEach(function (n) {
      var p = pos[n.id];
      var d = el("div", "af-node" + (p.judge ? " af-judge" : "") +
        (n.module || n.href ? " af-clickable" : ""), canvas);
      d.style.left = p.x - p.w / 2 + "px";
      d.style.top = p.y - p.h / 2 + "px";
      d.style.width = p.w + "px";
      d.style.height = p.h + "px";
      d.style.setProperty("--c", n.color || KIND_COLOR[n.kind] || KIND_COLOR.def);
      d.dataset.id = n.id;
      if (p.judge) {
        var dm = el("div", "af-diamond", d);
        var inner = el("div", "af-diamond-in", dm);
        inner.innerHTML = '<div class="af-node-label">' + esc(n.label) + "</div>" +
          (n.sub ? '<div class="af-node-sub">' + esc(n.sub) + "</div>" : "");
      } else {
        d.innerHTML = '<div class="af-node-label">' + esc(n.label) + "</div>" +
          (n.sub ? '<div class="af-node-sub">' + esc(n.sub) + "</div>" : "");
      }
      nodeEls[n.id] = d;

      // hover：高亮相连边与邻节点
      d.addEventListener("mouseenter", function () {
        canvas.classList.add("af-focus");
        d.classList.add("af-lit");
        edgeEls.forEach(function (g) {
          var f = g.getAttribute("data-from"), tt = g.getAttribute("data-to");
          if (f === n.id || tt === n.id) {
            g.classList.add("af-lit");
            if (nodeEls[f]) nodeEls[f].classList.add("af-lit");
            if (nodeEls[tt]) nodeEls[tt].classList.add("af-lit");
          }
        });
      });
      d.addEventListener("mouseleave", function () {
        canvas.classList.remove("af-focus");
        canvas.querySelectorAll(".af-lit").forEach(function (x) { x.classList.remove("af-lit"); });
      });
      // click：href 优先跳卷，否则带 module 的节点开抽屉
      if (n.href) d.addEventListener("click", function () { location.href = n.href; });
      else if (n.module) d.addEventListener("click", function () { openModule(data, n.module); });
    });

    // 图例
    if (Object.keys(types).length) {
      var legend = el("div", "af-legend", box);
      Object.keys(types).forEach(function (k) {
        var t = types[k];
        var chip = el("span", "af-legend-item", legend);
        var line = svg("svg", { width: 26, height: 10 }, chip);
        var la = { x1: 1, y1: 5, x2: 19, y2: 5, stroke: t.color, "stroke-width": 2 };
        if (t.dash) la["stroke-dasharray"] = t.dash;
        svg("line", la, line);
        svg("path", { d: "M19,1.5 L25,5 L19,8.5 z", fill: t.color }, line);
        var nm = el("span", "", chip);
        nm.textContent = t.name || k;
      });
    }
    box._afData = data;
  }

  // ---------- 抽屉（模块详情） ----------
  var drawer = null, backdrop = null;

  function ensureDrawer() {
    if (drawer) return;
    backdrop = el("div", "af-backdrop", document.body);
    drawer = el("aside", "af-drawer", document.body);
    backdrop.addEventListener("click", closeDrawer);
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") closeDrawer();
    });
  }
  function closeDrawer() {
    if (!drawer) return;
    drawer.classList.remove("open");
    backdrop.classList.remove("open");
  }
  function section(title, bodyHtml) {
    return '<section class="af-sec"><h4>' + esc(title) + "</h4>" + bodyHtml + "</section>";
  }

  function openModule(data, id) {
    var m = (data.modules || {})[id];
    if (!m) return;
    ensureDrawer();
    var catName = m.cat || "";
    (data.categories || []).forEach(function (c) {
      if (c.id === m.cat) catName = c.name || c.id;
    });
    var h = '<header class="af-dr-head">' +
      '<button class="af-dr-close" aria-label="关闭">×</button>' +
      '<div class="af-dr-tags">' +
      '<span class="af-chip">' + esc(catName) + "</span>" +
      (m.source ? '<span class="af-chip af-chip-ghost">' + esc(m.source) + "</span>" : "") +
      "</div>" +
      '<h3 class="af-dr-title">' + esc(m.label || id) + "</h3>" +
      '<div class="af-dr-id">' + esc(id) + "</div></header><div class='af-dr-body'>";
    if (m.purpose) h += section("定位", '<p class="af-p">' + esc(m.purpose) + "</p>");
    if (m.input || m.output) {
      h += section("输入 / 输出",
        (m.input ? ioRow("in", "IN", m.input, m.input_example) : "") +
        (m.output ? ioRow("out", "OUT", m.output, m.output_example) : ""));
    }
    if (m.logic && m.logic.length) {
      h += section("工作逻辑", "<ol>" + m.logic.map(function (x) { return "<li>" + esc(x) + "</li>"; }).join("") + "</ol>");
    }
    if (m.decisions && m.decisions.length) {
      h += section("判断规则", '<table class="af-dec">' +
        m.decisions.map(function (dd) {
          return "<tr><td>" + esc(dd.cond) + '</td><td class="af-dec-to">→ ' + esc(dd.to) + "</td></tr>";
        }).join("") + "</table>");
    }
    if (m.provides) h += section("提供能力", '<p class="af-p">' + esc(Array.isArray(m.provides) ? m.provides.join("；") : m.provides) + "</p>");
    h += "</div>";
    drawer.innerHTML = h;
    drawer.querySelector(".af-dr-close").addEventListener("click", closeDrawer);
    drawer.classList.add("open");
    backdrop.classList.add("open");
  }

  // ---------- 初始化 ----------
  function readData(box) {
    var sc = box.querySelector('script[type="application/json"]');
    var raw = sc ? sc.textContent : box.getAttribute("data-graph");
    if (!raw) return null;
    try { return JSON.parse(raw); } catch (e) { console.error("arch-flow: 数据 JSON 解析失败", e); return null; }
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll(".arch-flow").forEach(function (box) {
      var data = readData(box);
      if (data) render(box, data);
    });
  });

  window.ArchFlow = { render: render, openModule: openModule, closeDrawer: closeDrawer };
})();
