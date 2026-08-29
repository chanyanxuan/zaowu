// ====== 新版 UI 增强 ======
function toast(msg, type) {
  const box = document.getElementById('toasts');
  if (!box) { alert(msg); return; }
  const el = document.createElement('div');
  el.className = 'toast ' + (type || 'ok');
  const ic = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  ic.setAttribute('class', 'ic');
  ic.setAttribute('style', 'width:16px;height:16px;');
  const use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
  use.setAttribute('href', '#' + (type === 'err' ? 'i-close' : 'i-check'));
  ic.appendChild(use);
  const sp = document.createElement('span');
  sp.textContent = msg;
  el.appendChild(ic); el.appendChild(sp);
  box.appendChild(el);
  setTimeout(() => { el.classList.add('out'); setTimeout(() => el.remove(), 350); }, 3400);
}
document.getElementById('year').textContent = new Date().getFullYear();

// ---- 交付仪式:收进度、亮舞台、盖章 ----
function theaterDeliver() {
  document.body.classList.remove('generating');
  const prog = document.getElementById('progress');
  if (prog) prog.style.display = 'none';
  const stg = document.getElementById('result');
  if (stg) {
    stg.classList.remove('has-result');
    void stg.offsetWidth;          // 重新触发动画
    stg.classList.add('has-result');
  }
}

// ---- 生成阶段步骤(由 setStage/showResult 驱动) ----
function uiStage(text) {
  const box = document.getElementById('stages');
  if (!box) return;
  const s = String(text || '');
  let idx = 0;
  if (s.includes('排队') || s.includes('看图') || s.includes('工程规格') || s.includes('外观') || s.includes('理解')) idx = 0;
  else if (s.includes('确认')) idx = 1;
  else if (s.includes('生成') || s.includes('修正') || s.includes('绘制') || s.includes('建模')) idx = 2;
  const steps = box.querySelectorAll('.stage-step');
  steps.forEach((el, i) => {
    el.classList.remove('on', 'working', 'done');
    if (i < idx) el.classList.add('done');
    else if (i === idx) { el.classList.add('on'); if (i === 2) el.classList.add('working'); }
  });
}
function uiStageDone() {
  const box = document.getElementById('stages');
  if (!box) return;
  box.querySelectorAll('.stage-step').forEach(el => {
    el.classList.remove('on', 'working');
    el.classList.add('done');
  });
}

// ---- 滚动显现 ----
(function revealInit() {
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  document.querySelectorAll('.faq-item, .compat, .price-card').forEach(el => { if (!el.classList.contains('reveal')) el.classList.add('reveal'); });
  const els = document.querySelectorAll('.reveal');
  if (!('IntersectionObserver' in window)) { els.forEach(el => el.classList.add('in')); return; }
  const io = new IntersectionObserver(entries => {
    entries.forEach(en => {
      if (en.isIntersecting) { en.target.classList.add('in'); io.unobserve(en.target); }
    });
  }, { threshold: 0.12, rootMargin: '0px 0px -40px 0px' });
  els.forEach(el => io.observe(el));
})();

// ---- Hero 截图 3D 视差 ----
(function tiltInit() {
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  const visual = document.getElementById('heroVisual');
  const tilt = document.getElementById('heroTilt');
  if (!visual || !tilt) return;
  visual.addEventListener('mousemove', e => {
    const r = visual.getBoundingClientRect();
    const px = (e.clientX - r.left) / r.width - 0.5;
    const py = (e.clientY - r.top) / r.height - 0.5;
    tilt.style.transform = `rotateY(${px * 10}deg) rotateX(${-py * 8}deg)`;
  });
  visual.addEventListener('mouseleave', () => { tilt.style.transform = 'rotateY(0) rotateX(0)'; });
})();

// ---- 数字滚动 ----
(function countInit() {
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  const nums = document.querySelectorAll('.cnt[data-count]');
  if (!nums.length || !('IntersectionObserver' in window)) return;
  const io = new IntersectionObserver(entries => {
    entries.forEach(en => {
      if (!en.isIntersecting) return;
      const el = en.target;
      io.unobserve(el);
      const target = Number(el.dataset.count) || 0;
      const t0 = performance.now();
      const dur = 900;
      const tick = now => {
        const p = Math.min(1, (now - t0) / dur);
        const eased = 1 - Math.pow(1 - p, 3);
        el.textContent = Math.round(target * eased);
        if (p < 1) requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    });
  }, { threshold: 0.6 });
  nums.forEach(el => io.observe(el));
})();

// ---- 快捷示例 ----
document.querySelectorAll('.quick-row .chip').forEach(b => {
  b.addEventListener('click', () => { note.value = b.dataset.example; note.focus(); });
});

// ---- 案例大图灯箱 ----
document.querySelectorAll('.case img').forEach(img => {
  img.addEventListener('click', () => {
    document.getElementById('picImg').src = img.src;
    document.getElementById('picOverlay').classList.add('show');
  });
});
document.getElementById('picOverlay').addEventListener('click', e => {
  if (e.target.id === 'picOverlay' || e.target.classList.contains('pic-close')) {
    document.getElementById('picOverlay').classList.remove('show');
  }
});

// ---- 三维预览深色主题(与全站一致;已设置过则尊重用户选择) ----
(function viewerTheme() {
  try {
    if (!localStorage.getItem('cad-viewer:color-scheme')) {
      localStorage.setItem('cad-viewer:color-scheme', 'dark');
    }
  } catch (e) {}
})();

// ---- 交付单页签 ----
document.querySelectorAll('.spec-tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.spec-tab').forEach(t => t.classList.remove('on'));
    document.querySelectorAll('.spec-pane').forEach(p => p.classList.remove('on'));
    tab.classList.add('on');
    const pane = document.getElementById(tab.dataset.tab);
    if (pane) pane.classList.add('on');
  });
});

// ---- 页脚反馈入口 ----
document.getElementById('fbFooterLink').addEventListener('click', e => {
  e.preventDefault();
  document.getElementById('fbOverlay').classList.add('show');
});

// ---- 顶部阅读进度条 + 导航滚动状态 ----
(function scrollFx() {
  const bar = document.getElementById('readbar');
  const nav = document.querySelector('.nav');
  let ticking = false;
  const update = () => {
    ticking = false;
    const h = document.documentElement;
    const max = h.scrollHeight - h.clientHeight;
    if (bar) bar.style.width = (max > 0 ? (h.scrollTop / max) * 100 : 0) + '%';
    if (nav) nav.classList.toggle('scrolled', h.scrollTop > 10);
  };
  window.addEventListener('scroll', () => { if (!ticking) { ticking = true; requestAnimationFrame(update); } }, { passive: true });
  update();
})();

// ---- 卡片聚光灯 ----
(function spotFx() {
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  document.querySelectorAll('.spot').forEach(card => {
    card.addEventListener('pointermove', e => {
      const r = card.getBoundingClientRect();
      card.style.setProperty('--mx', (e.clientX - r.left) + 'px');
      card.style.setProperty('--my', (e.clientY - r.top) + 'px');
    }, { passive: true });
  });
})();

// ---- 标准件库 ----
(function stdlib() {
  const grid = document.getElementById('libGrid');
  const catsBox = document.getElementById('libCats');
  if (!grid || !catsBox) return;
  let CATALOG = null, currentPart = null;

  async function load() {
    let lastErr = null;
    for (let i = 0; i < 3; i++) {
      try {
        const r = await fetch('/api/library/catalog');
        const d = await r.json();
        CATALOG = d;
        renderCats('all');
        renderCards('all');
        return;
      } catch (e) { lastErr = e; }
      await new Promise(res => setTimeout(res, 1200));
    }
    grid.innerHTML = '<div class="hint" style="grid-column:1/-1;">标准件库加载失败: ' + (lastErr && lastErr.message || '') +
      ' <button class="mini ghost" id="libRetry">点此重试</button></div>';
    const rb = document.getElementById('libRetry');
    if (rb) rb.onclick = () => { grid.innerHTML = '<div class="hint">加载中…</div>'; load(); };
  }
  function allParts() {
    const native = (CATALOG && CATALOG.catalog || []).flatMap(c => c.parts);
    const oscad = (CATALOG && CATALOG.oscad || []).map(e => Object.assign({}, e, { oscad: true, standard: e.source || '' }));
    return native.concat(oscad);
  }
  function renderCats(active) {
    catsBox.innerHTML = '';
    const seen = new Set(['all']);
    const cats = [['all', '全部']];
    (CATALOG.catalog || []).forEach(c => { if (!seen.has(c.category)) { seen.add(c.category); cats.push([c.category, c.category]); } });
    (CATALOG.oscad || []).forEach(e => { if (!seen.has(e.category)) { seen.add(e.category); cats.push([e.category, e.category]); } });
    cats.forEach(([k, label]) => {
      const b = document.createElement('button');
      b.className = 'flt' + (active === k ? ' on' : '');
      b.textContent = label;
      b.onclick = () => { renderCats(k); renderCards(k); };
      catsBox.appendChild(b);
    });
  }
  function renderCards(cat) {
    const parts = allParts().filter(p => cat === 'all' || p.category === cat);
    grid.innerHTML = parts.map(p => `
      <div class="lib-card" data-id="${p.id}">
        <div class="lib-ic"><svg class="ic"><use href="#i-${p.oscad ? 'layers' : 'cube'}"/></svg></div>
        <div class="lib-name">${p.name}${p.oscad ? ' <span class="lib-badge">打印</span>' : ''}</div>
        <div class="lib-desc">${p.desc}</div>
        <div class="lib-std">${p.standard}</div>
      </div>`).join('') || '<div class="hint">该分类暂无零件</div>';
    grid.querySelectorAll('.lib-card').forEach(c => { c.onclick = () => openPart(c.dataset.id); });
  }
  function openPart(id) {
    currentPart = allParts().find(p => p.id === id);
    if (!currentPart) return;
    document.getElementById('libTitle').textContent = currentPart.name;
    document.getElementById('libStandard').textContent = currentPart.standard;
    const box = document.getElementById('libParams');
    box.innerHTML = currentPart.params.map(p => {
      if (p.kind === 'options') {
        return `<div class="lib-param"><label>${p.label}</label><select data-k="${p.key}">${
          (p.options || []).map(o => `<option value="${o}" ${String(o) === String(p.default) ? 'selected' : ''}>${o}</option>`).join('')
        }</select></div>`;
      }
      return `<div class="lib-param"><label>${p.label}(${p.unit})</label><input type="number" data-k="${p.key}" value="${p.default}" min="${p.min}" max="${p.max}" step="${p.step || 1}"></div>`;
    }).join('') || '<div class="hint">该零件无参数</div>';
    document.getElementById('libResult').style.display = 'none';
    document.getElementById('libStatus').textContent = '';
    document.getElementById('libOverlay').classList.add('show');
  }
  document.getElementById('libClose').onclick = () => document.getElementById('libOverlay').classList.remove('show');
  document.getElementById('libOverlay').addEventListener('click', e => {
    if (e.target.id === 'libOverlay') e.target.classList.remove('show');
  });
  // 预览窗口只显示 3D 模型:向同源 iframe 注入样式,隐藏查看器界面 chrome
  function stripViewerChrome() {
    const fr = document.getElementById('libViewer');
    if (!fr) return;
    try {
      const d = fr.contentDocument;
      if (!d || !d.head) return;
      if (d.getElementById('zw-strip')) return;
      const st = d.createElement('style');
      st.id = 'zw-strip';
      st.textContent = [
        'header, aside { display:none !important; }',
        '.cad-glass-surface { display:none !important; }',
        'button, [role="button"], [data-slot="sidebar-trigger"] { display:none !important; }',
        'main, [data-slot="sidebar-wrapper"] { border:none !important; margin:0 !important; padding:0 !important; }',
      ].join('\n');
      d.head.appendChild(st);
    } catch (e) {}
  }
  document.getElementById('libViewer').onload = () => { setTimeout(stripViewerChrome, 400); stripViewerChrome(); };
  // 渲染等待:轮询画布出现,期间显示加载遮罩;渲染失败给出提示
  let libTimer = null;
  function watchViewerReady() {
    const fr = document.getElementById('libViewer');
    const loadEl = document.getElementById('libLoading');
    const timeoutEl = document.getElementById('libTimeout');
    let ready = false, failed = '';
    try {
      const doc = fr && fr.contentDocument;
      if (doc) {
        ready = !!doc.querySelector('canvas[data-engine]');
        const t = (doc.body && doc.body.innerText) || '';
        if (t.includes('Render artifact build failed') || t.includes('No module named')) {
          failed = t.split('\n').find(x => x.includes('failed') || x.includes('No module')) || '模型渲染失败';
        }
      }
    } catch (e) {}
    if (failed) {
      if (loadEl) loadEl.style.display = 'none';
      if (timeoutEl) {
        timeoutEl.style.display = 'flex';
        timeoutEl.querySelector('span').textContent = failed + '。';
      }
      return;
    }
    if (ready) {
      if (loadEl) loadEl.style.display = 'none';
      return;
    }
    if (!watchViewerReady._tries) watchViewerReady._tries = 0;
    if (++watchViewerReady._tries > 60) {
      if (loadEl) loadEl.style.display = 'none';
      if (timeoutEl) timeoutEl.style.display = 'flex';
      return;
    }
    libTimer = setTimeout(watchViewerReady, 2000);
  }
  document.getElementById('libGo').onclick = async () => {
    if (!currentPart) return;
    const params = {};
    document.querySelectorAll('#libParams [data-k]').forEach(el => { params[el.dataset.k] = el.value; });
    const st = document.getElementById('libStatus');
    const btn = document.getElementById('libGo');
    const stepLink = document.getElementById('libStep');
    st.textContent = currentPart.oscad ? '渲染中…' : '生成中…';
    btn.disabled = true;
    try {
      const url = currentPart.oscad ? '/api/library/oscad' : '/api/library/build';
      const body = currentPart.oscad ? { id: currentPart.id, params } : { part_id: currentPart.id, params };
      const r = await fetch(url, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const d = await r.json();
      if (d.error) throw new Error(d.error);
      const res = document.getElementById('libResult');
      res.style.display = 'block';
      stepLink.style.display = currentPart.oscad ? 'none' : '';
      stepLink.href = d.step_url || '';
      document.getElementById('libStl').href = d.stl_url;
      document.getElementById('libOpenExt').href = d.viewer_url;
      const loadEl = document.getElementById('libLoading');
      if (loadEl) { loadEl.style.display = 'flex'; }
      document.getElementById('libTimeout').style.display = 'none';
      watchViewerReady._tries = 0;
      document.getElementById('libViewer').src = d.viewer_url;
      watchViewerReady();
      st.textContent = '已生成 ✓';
    } catch (e) {
      st.textContent = '出错: ' + e.message;
    }
    btn.disabled = false;
  };
  load();
})();

// ---- step.parts 外部零件检索 ----
(function extLib() {
  const q = document.getElementById('extQ');
  const go = document.getElementById('extGo');
  const box = document.getElementById('extResults');
  if (!q || !go || !box) return;
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  // 中文关键词 -> 英文检索词(step.parts 索引为英文)
  const ZH2EN = [
    ['内六角沉头', 'hex socket countersunk'], ['内六角', 'socket head'], ['圆柱头', 'socket head'],
    ['沉头', 'countersunk'], ['六角', 'hex'], ['十字', 'phillips'],
    ['轴承座', 'bearing block'], ['轴承', 'bearing'], ['垫圈', 'washer'],
    ['螺栓', 'bolt'], ['螺丝', 'screw'], ['螺钉', 'screw'], ['螺母', 'nut'],
    ['齿轮', 'gear'], ['步进电机', 'stepper motor'], ['电机', 'motor'],
    ['铝型材', 'aluminium extrusion'], ['丝杆', 'leadscrew'], ['联轴器', 'coupling'],
    ['直线导轨', 'linear rail'], ['导轨', 'rail'], ['弹簧', 'spring'], ['销', 'pin'],
  ];
  function toEnQuery(s) {
    ZH2EN.forEach(([zh, en]) => { s = s.split(zh).join(' ' + en + ' '); });
    return s.replace(/\s+/g, ' ').trim();
  }
  async function search() {
    let val = q.value.trim();
    if (val.length < 2) { box.innerHTML = '<div class="hint">请输入关键词,或点上面的「一键搜」按钮</div>'; return; }
    const zh = /[\u4e00-\u9fa5]/.test(val);
    val = toEnQuery(val);
    box.innerHTML = '<div class="hint">检索中…</div>';
    try {
      const r = await fetch('/api/library/stepparts?q=' + encodeURIComponent(val));
      const d = await r.json();
      if (d.error) throw new Error(d.error);
      if (!d.items || !d.items.length) {
        box.innerHTML = '<div class="hint">没有找到匹配的零件' + (zh ? '(中文词已按“' + esc(val) + '”检索)' : '') + ',换个说法或型号试试</div>';
        return;
      }
      box.innerHTML = d.items.map(it => `
        <div class="ext-item">
          <div class="ext-name">${esc(it.name)}</div>
          <div class="ext-meta">${esc(it.standard || '')}${Object.entries(it.attrs || {}).slice(0, 4).map(([k, v]) => esc(k) + ': ' + esc(v)).join(' · ')}</div>
          <div class="ext-acts">
            <button class="mini" data-dl data-url="${encodeURIComponent(it.step_url || '')}" data-id="${esc(it.id)}">下载 STEP</button>
            <a class="mini ghost" href="${esc(it.page_url)}" target="_blank" rel="noopener">原页 ↗</a>
          </div>
        </div>`).join('');
      box.querySelectorAll('[data-dl]').forEach(btn => {
        btn.onclick = async () => {
          btn.disabled = true;
          const old = btn.textContent;
          btn.textContent = '下载中…';
          try {
            const rr = await fetch('/api/library/stepparts/download', {
              method: 'POST', headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ id: btn.dataset.id, step_url: decodeURIComponent(btn.dataset.url) }),
            });
            const dd = await rr.json();
            if (dd.error) throw new Error(dd.error);
            const a = document.createElement('a');
            a.href = dd.step_url; a.download = ''; document.body.appendChild(a); a.click(); a.remove();
            btn.textContent = '已下载 ✓';
            const acts = btn.closest('.ext-acts');
            if (acts && dd.viewer_url && !acts.querySelector('.ext-preview')) {
              const pv = document.createElement('a');
              pv.className = 'mini ghost ext-preview';
              pv.href = dd.viewer_url; pv.target = '_blank'; pv.rel = 'noopener';
              pv.textContent = '预览 ↗';
              acts.insertBefore(pv, acts.lastElementChild);
            }
          } catch (e) {
            btn.textContent = old;
            toast('下载失败: ' + e.message, 'err');
          }
          btn.disabled = false;
        };
      });
    } catch (e) {
      box.innerHTML = '<div class="hint">检索失败: ' + esc(e.message) + '</div>';
    }
  }
  go.onclick = search;
  q.addEventListener('keydown', e => { if (e.key === 'Enter') search(); });
  // 一键搜
  document.querySelectorAll('#extQuick .chip').forEach(ch => {
    ch.onclick = () => { q.value = ch.dataset.q; search(); };
  });
})();
