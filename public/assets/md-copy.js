/* md-copy.js — 「复制 MD 链接」藏书章悬浮球
 * 自包含：自带样式（scoped 在 #md-copy-seal 下），不依赖报告自身的 CSS，
 * 因此新老两代报告通用。模板与存量报告各注入一行 <script> 即可。
 *
 * MD 链接是确定性的：与当前 .html 同路径，仅后缀不同。
 * 兼容 http 非安全环境（navigator.clipboard 不可用时回落 execCommand）。
 */
(function () {
  'use strict';
  if (window.__mdCopySealLoaded) return;
  window.__mdCopySealLoaded = true;

  var CSS = [
    '#md-copy-seal{position:fixed;right:26px;bottom:26px;z-index:9999;',
    '  font-family:"JetBrains Mono","Noto Sans SC",monospace;',
    '  opacity:0;transform:translateY(14px);transition:opacity .5s ease,transform .5s cubic-bezier(.22,1,.36,1);}',
    '#md-copy-seal.on{opacity:1;transform:translateY(0);}',
    '#md-copy-seal .seal{position:relative;display:flex;align-items:center;justify-content:center;',
    '  width:52px;height:52px;border-radius:9px;cursor:pointer;border:none;',
    '  background:#A63A2E;color:#FBFAF7;font-size:17px;font-weight:700;letter-spacing:1px;',
    '  box-shadow:0 3px 10px rgba(166,58,46,.35),0 1px 3px rgba(35,39,46,.2);',
    '  transition:transform .18s ease,box-shadow .18s ease,background .25s ease;}',
    '#md-copy-seal .seal:hover{transform:translateY(-3px) rotate(-2deg);',
    '  box-shadow:0 8px 20px rgba(166,58,46,.42),0 2px 6px rgba(35,39,46,.22);}',
    '#md-copy-seal .seal:active{transform:translateY(0) scale(.92) rotate(-2deg);}',
    '#md-copy-seal .seal .glyph{transition:opacity .15s ease,transform .15s ease;}',
    '#md-copy-seal .seal .check{position:absolute;opacity:0;transform:scale(.4);',
    '  transition:opacity .2s ease,transform .25s cubic-bezier(.34,1.56,.64,1);font-size:20px;}',
    '#md-copy-seal.done .seal{background:#2E7D4F;}',
    '#md-copy-seal.done .glyph{opacity:0;transform:scale(.4);}',
    '#md-copy-seal.done .check{opacity:1;transform:scale(1);}',
    /* 盖章涟漪 */
    '#md-copy-seal .seal::after{content:"";position:absolute;inset:0;border-radius:9px;',
    '  border:2px solid rgba(166,58,46,.55);opacity:0;pointer-events:none;}',
    '#md-copy-seal.done .seal::after{animation:mdseal-ripple .6s ease-out;}',
    '@keyframes mdseal-ripple{0%{opacity:.8;transform:scale(1);}100%{opacity:0;transform:scale(1.7);}}',
    /* 左侧滑出标签 */
    '#md-copy-seal .label{position:absolute;right:62px;top:50%;transform:translate(8px,-50%);',
    '  white-space:nowrap;background:#23272E;color:#FBFAF7;font-size:12px;font-weight:500;',
    '  padding:6px 11px;border-radius:6px;opacity:0;pointer-events:none;',
    '  transition:opacity .2s ease,transform .25s cubic-bezier(.22,1,.36,1);',
    '  box-shadow:0 2px 8px rgba(35,39,46,.25);}',
    '#md-copy-seal .label::after{content:"";position:absolute;left:100%;top:50%;transform:translateY(-50%);',
    '  border:5px solid transparent;border-left-color:#23272E;}',
    '#md-copy-seal:hover .label,#md-copy-seal.done .label{opacity:1;transform:translate(0,-50%);}',
    '@media print{#md-copy-seal{display:none;}}',
    '@media (prefers-reduced-motion:reduce){#md-copy-seal,#md-copy-seal *{transition:none;animation:none;}}'
  ].join('\n');

  function mdUrl() {
    var u = location.href.split('#')[0].split('?')[0];
    return u.replace(/\.html?$/i, '.md');
  }

  function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(text);
    }
    return new Promise(function (resolve, reject) {
      var ta = document.createElement('textarea');
      ta.value = text;
      ta.style.cssText = 'position:fixed;opacity:0;pointer-events:none;';
      document.body.appendChild(ta);
      ta.focus(); ta.select();
      try { document.execCommand('copy') ? resolve() : reject(new Error('copy failed')); }
      catch (e) { reject(e); }
      finally { document.body.removeChild(ta); }
    });
  }

  function build() {
    var style = document.createElement('style');
    style.textContent = CSS;
    document.head.appendChild(style);

    var root = document.createElement('div');
    root.id = 'md-copy-seal';
    root.innerHTML =
      '<button class="seal" type="button" aria-label="复制 Markdown 链接">' +
        '<span class="glyph">MD</span><span class="check">✓</span>' +
      '</button>' +
      '<span class="label">复制 MD 链接给 AI</span>';
    document.body.appendChild(root);

    var label = root.querySelector('.label');
    var timer = null;

    root.querySelector('.seal').addEventListener('click', function () {
      copyText(mdUrl()).then(function () {
        root.classList.add('done');
        label.textContent = '已复制 MD 链接 ✓';
        clearTimeout(timer);
        timer = setTimeout(function () {
          root.classList.remove('done');
          label.textContent = '复制 MD 链接给 AI';
        }, 1600);
      }).catch(function () {
        label.textContent = '复制失败，请手动改后缀为 .md';
        clearTimeout(timer);
        timer = setTimeout(function () { label.textContent = '复制 MD 链接给 AI'; }, 2200);
      });
    });

    // 入场：等首屏渲染后淡入
    requestAnimationFrame(function () { requestAnimationFrame(function () { root.classList.add('on'); }); });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', build);
  } else {
    build();
  }
})();
