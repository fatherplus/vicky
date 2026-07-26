// ai-report mermaid 初始化 v1 —— 仅在使用了 <pre class="mermaid"> 契约的报告里被注入
document.addEventListener("DOMContentLoaded", () => {
  if (!window.mermaid) return; // 资产 404/离线 → 源码保持代码块可读，整页不挂
  mermaid.initialize({ startOnLoad: false, theme: "neutral" });
  const pres = document.querySelectorAll("pre.mermaid");
  if (!pres.length) return;
  pres.forEach((pre) => {
    const node = document.createElement("div");
    node.className = "mermaid";
    node.textContent = pre.textContent;
    pre.replaceWith(node);
  });
  mermaid.run({ nodes: document.querySelectorAll(".mermaid") });
});
