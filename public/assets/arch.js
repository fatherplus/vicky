/* Vicky 架构导航器共享脚本：极简 Markdown 渲染（抽屉用）+ SVG 连线落位。
   导航页（views/arch.html）与模块子页（views/arch-module.html）复用。 */

function _archEsc(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function _archInline(s) {
  return s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
          .replace(/`([^`]+)`/g, "<code>$1</code>");
}

/* 极简 Markdown → HTML（抽屉按需渲染 API 返回的 body_md）。
   ponytail：不引入 marked 等依赖，够架构正文用即可。 */
function archRenderMD(md) {
  var lines = _archEsc(md || "").split("\n");
  var html = [], inCode = false, codeBuf = [], listBuf = [];
  function flushList() {
    if (listBuf.length) {
      html.push("<ul>" + listBuf.map(function (x) { return "<li>" + x + "</li>"; }).join("") + "</ul>");
      listBuf = [];
    }
  }
  for (var i = 0; i < lines.length; i++) {
    var ln = lines[i];
    if (/^```/.test(ln)) {
      if (inCode) { html.push("<pre><code>" + codeBuf.join("\n") + "</code></pre>"); codeBuf = []; inCode = false; }
      else { flushList(); inCode = true; }
      continue;
    }
    if (inCode) { codeBuf.push(ln); continue; }
    var h = ln.match(/^(#{1,4})\s+(.*)/);
    if (h) { flushList(); var lvl = h[1].length + 1; html.push("<h" + lvl + ">" + _archInline(h[2]) + "</h" + lvl + ">"); continue; }
    if (/^\s*[-*]\s+/.test(ln)) { listBuf.push(_archInline(ln.replace(/^\s*[-*]\s+/, ""))); continue; }
    flushList();
    if (ln.trim() === "") continue;
    html.push("<p>" + _archInline(ln) + "</p>");
  }
  flushList();
  if (inCode && codeBuf.length) html.push("<pre><code>" + codeBuf.join("\n") + "</code></pre>");
  return html.join("\n");
}

/* 给服务端已生成的 <path class="arch-edge" data-from data-to> 与
   <text class="arch-edge-cond"> 按节点实际 DOM 位置补 d/x/y。
   源节点底部中心 → 目标节点顶部中心（分层纵向布局）。 */
function archPositionEdges(wrap) {
  if (!wrap) return;
  var svg = wrap.querySelector("svg#edges") || document.getElementById("edges");
  if (!svg) return;
  var wr = wrap.getBoundingClientRect();
  svg.setAttribute("width", wr.width);
  svg.setAttribute("height", wr.height);
  var byId = {};
  wrap.querySelectorAll(".arch-node").forEach(function (n) { byId[n.dataset.id] = n; });
  svg.querySelectorAll("path.arch-edge").forEach(function (p) {
    var a = byId[p.dataset.from], b = byId[p.dataset.to];
    if (!a || !b) return;
    var ar = a.getBoundingClientRect(), br = b.getBoundingClientRect();
    var x1 = ar.left + ar.width / 2 - wr.left, y1 = ar.top + ar.height - wr.top;
    var x2 = br.left + br.width / 2 - wr.left, y2 = br.top - wr.top;
    var my = (y1 + y2) / 2;
    p.setAttribute("d", "M" + x1 + "," + y1 + " C" + x1 + "," + my + " " + x2 + "," + my + " " + x2 + "," + y2);
  });
  svg.querySelectorAll("text.arch-edge-cond").forEach(function (t) {
    var a = byId[t.dataset.from], b = byId[t.dataset.to];
    if (!a || !b) return;
    var ar = a.getBoundingClientRect(), br = b.getBoundingClientRect();
    t.setAttribute("x", (ar.left + ar.width / 2 + br.left + br.width / 2) / 2 - wr.left);
    t.setAttribute("y", (ar.top + ar.height + br.top) / 2 - wr.top - 4);
  });
}
