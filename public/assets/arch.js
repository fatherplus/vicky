/* Vicky 架构导航器共享脚本：画布 pan/zoom/focus + SVG 连线落位。
   导航页（views/arch.html）复用；模块子页不加载 JS。 */

/* 给服务端已生成的 <path class="arch-edge" data-from data-to> 与
   <text class="arch-edge-cond"> 按节点在 #world 内的 offset 坐标补 d/x/y。
   用 offset 坐标（相对 #world），与缩放无关。 */
function archPositionEdges(world) {
  if (!world) return;
  var svg = world.querySelector("svg#edges");
  if (!svg) return;
  var byId = {};
  world.querySelectorAll(".arch-node").forEach(function (n) { byId[n.dataset.id] = n; });
  svg.querySelectorAll("path.arch-edge").forEach(function (p) {
    var a = byId[p.dataset.from], b = byId[p.dataset.to];
    if (!a || !b) return;
    var x1 = a.offsetLeft + a.offsetWidth / 2, y1 = a.offsetTop + a.offsetHeight;
    var x2 = b.offsetLeft + b.offsetWidth / 2, y2 = b.offsetTop;
    var my = (y1 + y2) / 2;
    p.setAttribute("d", "M" + x1 + "," + y1 + " C" + x1 + "," + my + " " + x2 + "," + my + " " + x2 + "," + y2);
  });
  svg.querySelectorAll("text.arch-edge-cond").forEach(function (t) {
    var a = byId[t.dataset.from], b = byId[t.dataset.to];
    if (!a || !b) return;
    t.setAttribute("x", (a.offsetLeft + a.offsetWidth / 2 + b.offsetLeft + b.offsetWidth / 2) / 2);
    t.setAttribute("y", (a.offsetTop + a.offsetHeight + b.offsetTop) / 2 - 4);
  });
}

/* 画布：滚轮朝光标缩放 + 拖拽平移 + 点节点聚焦。返回 {focusNode, zoomBy, reset}。 */
function archInitCanvas(world, viewport) {
  var MIN = 0.3, MAX = 2.5, scale = 1, tx = 0, ty = 0;
  function apply() { world.style.transform = "translate(" + tx + "px," + ty + "px) scale(" + scale + ")"; }
  function focusNode(id, zoomTo) {
    var el = world.querySelector('.arch-node[data-id="' + id + '"]');
    if (!el) return;
    world.querySelectorAll(".arch-node").forEach(function (n) { n.classList.toggle("focused", n === el); });
    scale = zoomTo || Math.max(scale, 1);
    var cx = el.offsetLeft + el.offsetWidth / 2, cy = el.offsetTop + el.offsetHeight / 2;
    tx = viewport.clientWidth / 2 - cx * scale; ty = viewport.clientHeight / 2 - cy * scale;
    world.style.transition = "transform .45s ease"; apply();
    setTimeout(function () { world.style.transition = ""; }, 480);
  }
  viewport.addEventListener("wheel", function (e) {
    e.preventDefault();
    var r = viewport.getBoundingClientRect(), cx = e.clientX - r.left, cy = e.clientY - r.top;
    var old = scale; scale = Math.min(MAX, Math.max(MIN, scale * (e.deltaY < 0 ? 1.1 : 1 / 1.1)));
    tx = cx - (cx - tx) * (scale / old); ty = cy - (cy - ty) * (scale / old); apply();
  }, { passive: false });
  var dragging = false, sx = 0, sy = 0;
  viewport.addEventListener("pointerdown", function (e) {
    if (e.target.closest && e.target.closest(".arch-node")) return;
    dragging = true; sx = e.clientX - tx; sy = e.clientY - ty; viewport.classList.add("dragging");
  });
  window.addEventListener("pointermove", function (e) {
    if (!dragging) return; tx = e.clientX - sx; ty = e.clientY - sy; apply();
  });
  window.addEventListener("pointerup", function () { dragging = false; viewport.classList.remove("dragging"); });
  function zoomBy(f) {
    var vw = viewport.clientWidth / 2, vh = viewport.clientHeight / 2, old = scale;
    scale = Math.min(MAX, Math.max(MIN, scale * f)); tx = vw - (vw - tx) * (scale / old); ty = vh - (vh - ty) * (scale / old); apply();
  }
  apply();
  return { focusNode: focusNode, zoomBy: zoomBy, reset: function () { scale = 1; tx = 0; ty = 0; apply(); } };
}
