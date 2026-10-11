/* Org Chart Inference: single-page frontend. Vanilla JS + Cytoscape (dagre) + Chart.js. */
(() => {
  'use strict';
  const $ = (s, el = document) => el.querySelector(s);
  const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
  const fmt = (x, d = 2) => (x === null || x === undefined || Number.isNaN(x)) ? '–' : Number(x).toFixed(d);
  const pct = (x, d = 1) => (x === null || x === undefined) ? '–' : (100 * x).toFixed(d) + '%';
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  const S = {
    page: 1, pageSize: 25, total: 0, q: '', industry: '', size: '', noise: '',
    payload: null, byId: new Map(), thr: 0.91, opThr: 0.91,
    rollups: true, collapse: true, unplaced: false, truth: false, dept: '',
    expanded: new Set(), open: new Set(), expandAll: false, foldLevel: 2, selected: null, cy: null, metrics: null, charts: {},
  };

  /* ---------- waking loader ---------- */
  async function wake() {
    const el = $('#waking');
    const showTimer = setTimeout(() => el.classList.add('visible'), 700);
    const t0 = Date.now();
    for (;;) {
      try {
        const r = await fetch('/health', { cache: 'no-store' });
        if (r.ok) break;
      } catch (_) { /* server still waking */ }
      if (Date.now() - t0 > 20000) $('#waking-msg').textContent = 'Still starting. Free hosting can take up to a minute after a quiet spell. Thanks for waiting.';
      await new Promise((res) => setTimeout(res, 2000));
    }
    clearTimeout(showTimer);
    el.classList.add('done');
    setTimeout(() => el.remove(), 500);
  }

  /* ---------- api ---------- */
  async function api(path, opts) {
    const r = await fetch(path, opts);
    if (!r.ok) {
      let msg = `Request failed (${r.status})`;
      try { msg = (await r.json()).detail || msg; } catch (_) {}
      throw new Error(msg);
    }
    return r.json();
  }

  /* ---------- routing ---------- */
  function route() {
    const tab = (location.hash || '#explore').slice(1).split('/')[0] || 'explore';
    for (const v of ['explore', 'metrics', 'upload', 'how']) {
      $('#view-' + v).hidden = v !== tab;
      const a = document.querySelector(`.tabs a[data-tab=${v}]`);
      if (a) a.toggleAttribute('aria-current', v === tab), v === tab && a.setAttribute('aria-current', 'page');
    }
    if (tab === 'metrics') loadMetrics();
    if (tab === 'explore' && S.cy) S.cy.resize();
    const m = location.hash.match(/^#explore\/(C\d{4})$/);
    if (m && (!S.payload || S.payload.company.company_id !== m[1])) openCompany(m[1]);
  }

  /* ---------- company picker ---------- */
  let qTimer;
  async function loadList() {
    const p = new URLSearchParams({ q: S.q, industry: S.industry, size: S.size, noise: S.noise, page: S.page, page_size: S.pageSize });
    const d = await api('/api/companies?' + p);
    S.total = d.total;
    fillFacet('#f-industry', d.facets.industry, 'All industries');
    fillFacet('#f-size', d.facets.size_bucket, 'All sizes');
    fillFacet('#f-noise', d.facets.noise_level, 'Any noise', (x) => x.replace('_', ' '));
    const ul = $('#company-list');
    ul.innerHTML = d.items.length ? '' : '<li class="muted text-sm p-3">No companies match. Clear a filter or try another name.</li>';
    for (const c of d.items) {
      const li = document.createElement('li');
      const cur = S.payload && S.payload.company.company_id === c.company_id;
      li.innerHTML = `<button type="button" aria-current="${cur}" data-id="${c.company_id}">
        <span class="nm">${esc(c.company_name)}</span><span class="pc mono" title="Precision / coverage against the answer key">${c.precision == null ? '–' : pct(c.precision, 0)} · ${pct(c.coverage, 0)}</span>
        <span class="sub">${esc(c.industry)} · ${c.n_employees} people · ${esc(c.noise_level.replace('_', ' '))}${c.split === 'test' ? ' · held-out' : ''}</span></button>`;
      ul.appendChild(li);
    }
    const pages = Math.max(1, Math.ceil(S.total / S.pageSize));
    $('#page-info').textContent = `${S.page} / ${pages} · ${S.total}`;
    $('#prev').disabled = S.page <= 1;
    $('#next').disabled = S.page >= pages;
  }
  function fillFacet(sel, values, label, f = (x) => x) {
    const el = $(sel);
    if (el.options.length > 1) return;
    for (const v of values) el.add(new Option(f(v), v));
  }

  /* ---------- open company ---------- */
  async function openCompany(id) {
    $('#c-name').textContent = 'Loading…';
    try {
      const d = await api('/api/company/' + id);
      setPayload(d);
      if (location.hash !== '#explore/' + id) history.replaceState(null, '', '#explore/' + id);
      document.querySelectorAll('#company-list button').forEach((b) => b.setAttribute('aria-current', b.dataset.id === id));
      closePicker();
    } catch (e) {
      $('#c-name').textContent = 'Could not load that company';
      $('#c-meta').textContent = e.message + '. Try again or pick another one.';
    }
  }

  function setPayload(d) {
    S.payload = d;
    S.byId = new Map(d.nodes.map((n) => [n.id, n]));
    S.opThr = d.threshold; S.thr = d.threshold;
    $('#thr').value = S.thr; $('#thr-out').textContent = fmt(S.thr);
    S.expanded.clear(); S.open.clear(); S.expandAll = false; S.selected = null; S.dept = '';
    const c = d.company;
    $('#c-name').textContent = c.company_name;
    $('#c-meta').textContent = [c.industry, c.country, c.size_bucket && c.size_bucket + ' band', c.noise_level && c.noise_level.replace('_', ' ') + ' data', c.split === 'test' ? 'held-out company' : c.split === 'train' ? 'training company' : null].filter(Boolean).join(' · ');
    const depts = [...new Set(d.nodes.map((n) => n.dept).filter(Boolean))].sort();
    const fd = $('#f-dept'); fd.length = 1; depts.forEach((x) => fd.add(new Option(x, x)));
    const isUpload = c.company_id === 'UPLOAD';
    $('#t-truth').disabled = isUpload; if (isUpload) { S.truth = false; $('#t-truth').checked = false; document.body.classList.remove('truth'); }
    $('#empty').hidden = true;
    hideDetails();
    draw(true);
  }

  /* ---------- graph model ---------- */
  function trueAncestors(id) {
    const out = new Set(); let cur = S.byId.get(id);
    for (let i = 0; i < 12 && cur && cur.true_manager_id; i++) { out.add(cur.true_manager_id); cur = S.byId.get(cur.true_manager_id); }
    return out;
  }
  function parentOf(n) {
    if (n.status === 'root') return null;
    if (n.manager_id && n.confidence >= S.thr) return { p: n.manager_id, kind: 'edge', conf: n.confidence };
    if (S.rollups && n.rollup_id && n.rollup_conf >= S.payload.rollup_threshold) return { p: n.rollup_id, kind: 'rollup', conf: n.rollup_conf };
    return null;
  }
  const bucket = (c) => c >= 0.9 ? '--c4' : c >= 0.8 ? '--c3' : c >= 0.6 ? '--c2' : '--c1';

  // View-only folding. Nodes at or above S.foldLevel (2 = VPs, 1 = execs, 0 = CEO only) are shown;
  // each shown node's deeper reports fold into one "+N directors" chip until the chip is opened.
  // Inference, metrics, the answer key and Export never see this.
  const ORPHANS = '__orphans';
  const lvlOf = (n) => (n.level == null ? 5 : n.level);
  function buildElements() {
    const nodes = S.payload.nodes.filter((n) => !n.duplicate_of);
    const par = new Map(); const kids = new Map();
    for (const n of nodes) {
      const p = parentOf(n);
      if (p && S.byId.has(p.p)) { par.set(n.id, p); if (!kids.has(p.p)) kids.set(p.p, []); kids.get(p.p).push(n.id); }
    }
    S.par = par;
    // department filter: keep dept members + their ancestors
    let keep = new Set(nodes.map((n) => n.id));
    if (S.dept) {
      keep = new Set();
      for (const n of nodes) if (n.dept === S.dept) {
        let cur = n.id;
        for (let i = 0; i < 12 && cur && !keep.has(cur); i++) { keep.add(cur); cur = par.get(cur)?.p; }
      }
    }
    const placed = (id) => par.has(id) || kids.has(id) || S.byId.get(id).status === 'root';
    // which nodes are shown, and what folds where
    const L = S.expandAll ? 99 : S.foldLevel;
    const shown = new Set(); const folds = new Map(); const queue = [];
    const fold = (at, id) => { if (!folds.has(at)) folds.set(at, []); folds.get(at).push(id); };
    for (const n of nodes) {
      if (!keep.has(n.id) || par.has(n.id)) continue;           // tree roots only
      if (!placed(n.id) && !S.unplaced) continue;
      if (n.status === 'root' || lvlOf(n) <= L || !placed(n.id) || S.open.has(ORPHANS)) { shown.add(n.id); queue.push(n.id); }
      else fold(ORPHANS, n.id);                                  // teams whose head has no known manager
    }
    while (queue.length) {
      const x = queue.shift();
      for (const k of kids.get(x) || []) {
        if (!keep.has(k)) continue;
        if (lvlOf(S.byId.get(k)) <= L || S.open.has(x)) { shown.add(k); queue.push(k); } else fold(x, k);
      }
    }
    const below = (id) => { let c = 0; const st = [...(kids.get(id) || [])]; while (st.length) { const k = st.pop(); if (!keep.has(k)) continue; c++; st.push(...(kids.get(k) || [])); } return c; };
    const els = []; const groups = new Map();
    for (const n of nodes) {
      if (!shown.has(n.id)) continue;
      const p = par.get(n.id);
      const leaf = !kids.has(n.id);
      if (S.collapse && p && leaf && n.level === 5 && !S.expanded.has(p.p)) {
        const gid = `g:${p.p}:${p.kind}`;
        if (!groups.has(gid)) groups.set(gid, { parent: p.p, kind: p.kind, ids: [], conf: 0, wrong: 0 });
        const g = groups.get(gid); g.ids.push(n.id); g.conf += p.conf;
        if (S.truth && !edgeCorrect(n, p)) g.wrong++;
        continue;
      }
      const cls = [n.level === 0 ? 'ceo' : n.level === 1 ? 'exec' : n.level === 2 || n.level === 3 ? 'lead' : '',
        placed(n.id) ? '' : 'unplaced', n.stale ? 'stale' : '', p ? '' : (n.status !== 'root' ? 'nomgr' : '')].filter(Boolean).join(' ');
      els.push({ data: { id: n.id, lvl: n.level, label: `${n.name}\n${n.title || 'No title'}` }, classes: cls });
      if (p && shown.has(p.p)) {
        const wrong = S.truth && !edgeCorrect(n, p);
        els.push({ data: { id: 'e:' + n.id, source: p.p, target: n.id, conf: p.conf, color: wrong ? css('--wrong') : css(bucket(p.conf)) }, classes: p.kind + (wrong ? ' wrong' : '') });
      }
    }
    for (const [gid, g] of groups) {
      const avg = g.conf / g.ids.length;
      const label = g.kind === 'edge' ? `${g.ids.length} IC${g.ids.length > 1 ? 's' : ''}` : `${g.ids.length} roll up here`;
      els.push({ data: { id: gid, label: label + (S.truth && g.wrong ? ` · ${g.wrong} wrong` : ''), group: g }, classes: 'group' + (g.kind === 'rollup' ? ' grp-rollup' : '') });
      els.push({ data: { id: 'e:' + gid, source: g.parent, target: gid, conf: avg, color: S.truth && g.wrong ? css('--wrong') : css(bucket(avg)) }, classes: g.kind });
    }
    const WORD = { 1: ['exec', 'execs'], 2: ['VP', 'VPs'], 3: ['director', 'directors'] };
    for (const [at, ids] of folds) {
      const lv = new Set(ids.map((i) => lvlOf(S.byId.get(i))));
      const w = lv.size === 1 && WORD[[...lv][0]] ? WORD[[...lv][0]] : ['report', 'reports'];
      const total = ids.length + ids.reduce((a, i) => a + below(i), 0);
      const head = at === ORPHANS ? `+${ids.length} team${ids.length > 1 ? 's' : ''}, no manager` : `+${ids.length} ${w[ids.length > 1 ? 1 : 0]}`;
      const fid = 'f:' + at;
      // answer key: count wrong links anywhere inside the fold (the chip edge itself and everything under it)
      let wrong = 0;
      if (S.truth) {
        const st = [...ids];
        while (st.length) { const k = st.pop(); if (!keep.has(k)) continue; const p = par.get(k); if (p && !edgeCorrect(S.byId.get(k), p)) wrong++; st.push(...(kids.get(k) || [])); }
      }
      els.push({ data: { id: fid, fold: at, wrong, label: `${head}\n${total} ${total === 1 ? 'person' : 'people'}` + (wrong ? `\n⚠ ${wrong} wrong` : '') }, classes: 'group fold' + (wrong ? ' fold-wrong' : '') });
      if (at === ORPHANS) {
        // invisible link so the layout puts this chip on the row under the CEO (keeps a phone view centred on the CEO)
        const root = L === 0 && nodes.find((n) => n.status === 'root' && shown.has(n.id));   // only when the CEO row is otherwise empty
        if (root) els.push({ data: { id: 'e:' + fid, source: root.id, target: fid, conf: 1, color: css('--line') }, classes: 'ghost' });
      } else {
        const confs = ids.map((i) => par.get(i).conf); const avg = confs.reduce((a, b) => a + b, 0) / confs.length;
        const allRoll = ids.every((i) => par.get(i).kind === 'rollup');
        els.push({ data: { id: 'e:' + fid, source: at, target: fid, conf: avg, color: css('--muted') }, classes: allRoll ? 'rollup' : 'edge' });
      }
    }
    return els;
  }
  function edgeCorrect(n, p) {
    if (p.kind === 'edge') return n.manager_id === n.true_manager_id || S.byId.get(n.manager_id)?.duplicate_of === n.true_manager_id ? true : !!n.proposed_correct && n.manager_id === p.p;
    return trueAncestors(n.id).has(p.p);
  }

  function style() {
    const ink = css('--node-ink'), node = css('--node'), line = css('--line'), muted = css('--muted'), accent = css('--accent');
    return [
      { selector: 'node', style: { shape: 'round-rectangle', width: 180, height: 56, 'background-color': node, 'border-width': 1, 'border-color': line,
        label: 'data(label)', 'text-wrap': 'wrap', 'text-max-width': 168, 'font-family': 'IBM Plex Sans, sans-serif', 'font-size': NODE_FONT, 'min-zoomed-font-size': 6, color: ink,
        'text-valign': 'center', 'text-halign': 'center', 'line-height': 1.25 } },
      { selector: 'node.ceo', style: { 'border-width': 2, 'border-color': accent, 'font-weight': 700 } },
      { selector: 'node.exec', style: { 'border-width': 1.5, 'border-color': accent } },
      { selector: 'node.lead', style: { 'border-color': muted } },
      { selector: 'node.nomgr', style: { 'border-style': 'dashed', 'border-color': muted, 'border-width': 1.5 } },
      { selector: 'node.unplaced', style: { 'border-style': 'dashed', 'background-opacity': 0.55 } },
      { selector: 'node.stale', style: { opacity: 0.6 } },
      { selector: 'node.group', style: { width: 132, height: 32, shape: 'round-rectangle', 'background-color': css('--line2'), 'border-width': 0, 'font-size': NODE_FONT, color: muted, 'font-weight': 600 } },
      { selector: 'node.fold', style: { width: 140, height: 48, 'background-color': css('--panel'), 'border-width': 1.5, 'border-style': 'dashed', 'border-color': accent, color: css('--accent'), 'text-max-width': 130 } },
      { selector: 'node.fold-wrong', style: { 'border-color': css('--wrong'), 'border-width': 2.5, 'border-style': 'solid', height: 66 } },
      { selector: 'node.grp-rollup', style: { 'border-width': 1, 'border-style': 'dashed', 'border-color': muted } },
      { selector: 'node:selected', style: { 'border-width': 2.5, 'border-color': accent, 'overlay-opacity': 0 } },
      { selector: 'node.dim', style: { opacity: 0.25 } },
      { selector: 'edge', style: { 'curve-style': 'taxi', 'taxi-direction': 'downward', 'taxi-turn': 24, width: 'mapData(conf, 0.5, 1, 1, 3.4)', 'line-color': 'data(color)', 'target-arrow-shape': 'none' } },
      { selector: 'edge.ghost', style: { opacity: 0, events: 'no' } },
      { selector: 'edge.rollup', style: { 'line-style': 'dashed', 'line-dash-pattern': [5, 4], width: 1.4 } },
      { selector: 'edge.wrong', style: { width: 3 } },
      { selector: 'edge.dim', style: { opacity: 0.15 } },
    ];
  }

  // view: 'auto' = pick the fold level so the first screen fits, then fit (load, upload, company change, Collapse)
  //       'fit'  = fit what is shown now, keeping the fold state (filters, Fit button, Expand all)
  //       'keep' = keep the user's viewport (slider drag)
  //       {expand: id} = keep the viewport, then pan just enough to bring the opened chip's subtree into view
  function layout() {
    S.cy.batch(() => { S.cy.elements().remove(); S.cy.add(buildElements()); });
    S.cy.layout({ name: 'dagre', rankDir: 'TB', nodeSep: 12, rankSep: 56, edgeSep: 6, animate: false, fit: false }).run();
  }
  function draw(animate, view = animate ? 'auto' : 'keep') {
    if (!S.payload) return;
    if (view === true) view = 'fit';
    if (!S.cy) {
      S.cy = cytoscape({ container: $('#cy'), elements: [], style: style(), minZoom: 0.05, maxZoom: 2.5, boxSelectionEnabled: false });
      S.cy.on('tap', 'node', (ev) => onTap(ev.target));
      S.cy.on('tap', (ev) => { if (ev.target === S.cy) { hideDetails(); clearDim(); } });
    }
    S.cy.resize();
    const vp = { zoom: S.cy.zoom(), pan: { ...S.cy.pan() } };
    let anchor = null;
    if (view && view.expand) { const a = S.cy.getElementById(view.expand); if (a.length) anchor = { id: view.expand, r: { ...a.renderedPosition() } }; }
    if (view === 'auto' && !S.expandAll) {
      for (const L of [2, 1, 0]) { S.foldLevel = L; layout(); if (fitZoom() >= MIN_ZOOM) break; }
    } else layout();
    if (view === 'auto' || view === 'fit') readableView();
    else if (anchor) revealSubtree(anchor, vp.zoom);
    else S.cy.viewport(vp);
    if (S.selected && S.cy.getElementById(S.selected).length) S.cy.getElementById(S.selected).select();
    if (animate) { const el = $('#cy'); el.classList.remove('enter'); void el.offsetWidth; el.classList.add('enter'); }
    $('#expand-all').textContent = S.expandAll ? 'Collapse' : 'Expand all';
    $('#expand-all').setAttribute('aria-pressed', S.expandAll);
    updateStats();
    const c = S.payload.company;
    $('#export').href = c.company_id === 'UPLOAD' ? '#' : `/api/company/${c.company_id}/export.csv?threshold=${S.thr}`;
  }

  // Fit what is shown with 40px padding, never below MIN_READABLE_PX labels, and always keep the CEO on
  // screen: centred with everything when it fits, otherwise centred on the CEO at the readable zoom.
  const MIN_READABLE_PX = 10;
  const NODE_FONT = 13;
  const MIN_ZOOM = MIN_READABLE_PX / NODE_FONT;
  const VIEW_PAD = 40;
  const shownBox = () => S.cy.nodes(':visible').boundingBox({ includeLabels: true, includeOverlays: false });
  function fitZoom() {
    const bb = shownBox();
    return Math.min((S.cy.width() - 2 * VIEW_PAD) / bb.w, (S.cy.height() - 2 * VIEW_PAD) / bb.h, 1.15);
  }
  function rootNode() {
    let r = S.cy.nodes('.ceo:visible').first();
    if (!r.length) r = S.cy.nodes(':visible').filter((n) => !n.hasClass('group')).sort((a, b) => a.position('y') - b.position('y') || a.position('x') - b.position('x')).first();
    return r;
  }
  function readableView() {
    const cy = S.cy, W = cy.width(), H = cy.height();
    if (!W || !H || !cy.nodes(':visible').length) return;
    const bb = shownBox();
    let z = fitZoom(), x;
    if (z >= MIN_ZOOM) {
      x = (W - bb.w * z) / 2 - bb.x1 * z; S.viewMode = 'fit';
      const r = rootNode(), xc = W / 2 - r.position('x') * z;   // prefer the CEO dead centre if the block still fits
      if (r.length && bb.x1 * z + xc >= VIEW_PAD - 0.5 && bb.x2 * z + xc <= W - VIEW_PAD + 0.5) x = xc;
    }
    else { z = MIN_ZOOM; const r = rootNode(); x = W / 2 - r.position('x') * z; S.viewMode = 'ceo-centred'; }
    const y = bb.h * z <= H - 2 * VIEW_PAD ? (H - bb.h * z) / 2 - bb.y1 * z : VIEW_PAD - bb.y1 * z;
    cy.viewport({ zoom: z, pan: { x, y } });
  }
  // After opening a chip: the clicked parent stays where it was, then we pan (not zoom) just enough to
  // bring its newly shown reports into view, without ever pushing the parent off screen.
  function revealSubtree(anchor, z) {
    const cy = S.cy, W = cy.width(), H = cy.height(), pad = 24;
    const a = cy.getElementById(anchor.id);
    cy.viewport({ zoom: z, pan: { x: anchor.r.x - a.position('x') * z, y: anchor.r.y - a.position('y') * z } });
    const sub = a.union(a.outgoers('node')).union(a.outgoers('node').outgoers('node'));
    const b = sub.renderedBoundingBox({ includeLabels: true });
    let dx = 0, dy = 0;
    const all = cy.nodes(':visible').renderedBoundingBox({ includeLabels: true });
    if (all.w <= W - 2 * pad && all.h <= H - 2 * pad) {     // whole chart fits at this zoom: just centre it
      cy.animate({ panBy: { x: (W - all.w) / 2 - all.x1, y: (H - all.h) / 2 - all.y1 } }, { duration: 280, easing: 'ease-out-cubic' });
      return;
    }
    if (b.x2 > W - pad) dx = W - pad - b.x2;
    if (b.x1 + dx < pad) dx = pad - b.x1;
    if (b.y2 > H - pad) dy = H - pad - b.y2;
    if (b.y1 + dy < pad) dy = pad - b.y1;
    const ar = a.renderedBoundingBox();                       // keep the parent itself on screen
    dx = Math.max(Math.min(dx, W - pad - ar.x2), pad - ar.x1);
    dy = Math.max(Math.min(dy, H - pad - ar.y2), pad - ar.y1);
    if (dx || dy) cy.animate({ panBy: { x: dx, y: dy } }, { duration: 280, easing: 'ease-out-cubic' });
  }
  // For checks: which visible nodes are not fully inside the canvas, and the smallest rendered label.
  function viewReport() {
    const cy = S.cy, W = cy.width(), H = cy.height(), z = cy.zoom();
    const vis = cy.nodes(':visible'); const out = []; let minPx = Infinity;
    vis.forEach((n) => {
      const b = n.renderedBoundingBox({ includeLabels: true });
      if (b.x1 < 0 || b.y1 < 0 || b.x2 > W || b.y2 > H) out.push(n.data('label').split('\n')[0]);
      minPx = Math.min(minPx, n.numericStyle('font-size') * z);
    });
    const r = rootNode(), rb = r.renderedBoundingBox();
    return { mode: S.viewMode, foldLevel: S.expandAll ? 'all' : S.foldLevel, zoom: +z.toFixed(3), labelPx: +minPx.toFixed(1),
      canvas: [W, H], visible: vis.length, chips: vis.filter('.fold').length, outside: out,
      ceoOnScreen: rb.x1 >= 0 && rb.x2 <= W && rb.y1 >= 0 && rb.y2 <= H, animating: cy.animated() };
  }

  function updateStats() {
    const nodes = S.payload.nodes;
    let edges = 0, rolls = 0, none = 0, ok = 0, haveTrue = 0;
    for (const n of nodes) {
      if (n.status === 'root') continue;
      const p = parentOf(n);
      if (p && p.kind === 'edge') { edges++; if (S.payload.company.split !== 'upload' && edgeCorrect(n, p)) ok++; }
      else if (p) rolls++; else none++;
      if (n.true_manager_id) haveTrue++;
    }
    const items = [['People', nodes.length], ['Edges', edges], ['Roll-ups', rolls], ['No manager', none]];
    if (S.payload.company.split !== 'upload' && haveTrue) items.push(['Precision', edges ? pct(ok / edges, 1) : '–']);
    $('#c-stats').innerHTML = items.map(([k, v]) => `<div><dt>${k}</dt><dd>${v}</dd></div>`).join('');
  }

  /* ---------- details ---------- */
  function onTap(el) {
    const g = el.data('group');
    if (g) { S.expanded.add(g.parent); draw(false, { expand: g.parent }); return; }
    const f = el.data('fold');
    if (f) { S.open.add(f); draw(false, f === ORPHANS ? 'keep' : { expand: f }); return; }
    S.selected = el.id(); showDetails(S.byId.get(el.id())); highlight(el);
  }
  function highlight(el) {
    clearDim();
    const keep = el.closedNeighborhood().union(el.predecessors()).union(el.successors());
    S.cy.elements().not(keep).addClass('dim');
  }
  function clearDim() { S.cy && S.cy.elements().removeClass('dim'); }
  function focus(id) {
    const el = S.cy.getElementById(id);
    if (!el.length) return;
    S.cy.animate({ center: { eles: el }, zoom: Math.max(S.cy.zoom(), 0.8) }, { duration: 300, easing: 'ease-out-cubic' });
    el.select(); S.selected = id; showDetails(S.byId.get(id)); highlight(el);
  }
  // Open every fold and IC group on the way from the top to this person, then draw.
  function revealPerson(id) {
    if (S.cy.getElementById(id).length) return;
    const n = S.byId.get(id); if (!n) return;
    let cur = id, top = id;
    for (let i = 0; i < 15; i++) { const p = S.par.get(cur); if (!p) break; S.open.add(p.p); S.expanded.add(p.p); top = cur = p.p; }
    S.open.add(ORPHANS);
    if (!S.par.get(id) && !(S.payload.nodes.some((x) => S.par.get(x.id)?.p === id)) && n.status !== 'root') { S.unplaced = true; $('#t-unplaced').checked = true; }
    draw(false, 'keep');
  }
  function personLink(id) {
    const p = S.byId.get(id);
    return p ? `<button class="link-btn" data-focus="${esc(id)}">${esc(p.name)}</button> <span class="muted">· ${esc(p.title || 'no title')}</span>` : esc(id);
  }
  function showDetails(n) {
    if (!n) return;
    $('#details').hidden = false;
    $('#d-name').textContent = n.name;
    const p = parentOf(n);
    const statusPill = n.status === 'root' ? '<span class="pill"><i class="dot" style="--c:var(--accent)"></i>Top of company</span>'
      : p?.kind === 'edge' ? `<span class="pill"><i class="dot" style="--c:var(${bucket(p.conf)})"></i>Direct manager · ${fmt(p.conf)}</span>`
      : p ? `<span class="pill"><i class="dot"></i>Rolls up to · ${fmt(p.conf)}</span>`
      : `<span class="pill"><i class="dot"></i>No confident manager${n.manager_id ? ` · best ${fmt(n.confidence)}` : ''}</span>`;
    const reports = S.payload.nodes.filter((x) => { const q = parentOf(x); return q && q.p === n.id; }).length;
    let truth = '';
    if (S.truth && n.true_manager_id !== undefined && S.payload.company.split !== 'upload') {
      const right = p ? edgeCorrect(n, p) : null;
      truth = `<section><h3 class="h3">Answer key</h3><dl class="kv"><dt>True manager</dt><dd>${n.true_manager_id ? personLink(n.true_manager_id) : '<span class="muted">none (CEO or someone who has left)</span>'}</dd>
        <dt>Shown link</dt><dd>${right === null ? 'none, abstained' : right ? 'correct' : '<b style="color:var(--wrong)">wrong</b>'}</dd></dl></section>`;
    }
    const cands = (n.candidates || []).map(([id, share]) => {
      const c = S.byId.get(id);
      return `<li><button data-focus="${esc(id)}"><span>${esc(c ? c.name : id)} <span class="muted">· ${esc(c?.title || '')}</span></span><span class="mono">${pct(share, 0)}</span><span class="bar"><i style="width:${Math.round(share * 100)}%"></i></span></button></li>`;
    }).join('');
    $('#d-body').innerHTML = `
      <div>${statusPill}</div>
      <dl class="kv">
        <dt>Raw title</dt><dd>${esc(n.title || '(missing)')}</dd>
        <dt>Dept field</dt><dd>${esc(n.department || '(missing)')}</dd>
        <dt>Read as</dt><dd>${esc([n.level_name, n.dept, n.specialty].filter(Boolean).join(' · ') || 'could not read this title')}</dd>
        <dt>Office</dt><dd>${esc(n.location || '(missing)')}</dd>
        <dt>Updated</dt><dd>${n.updated ? `<span class="mono">${esc(n.updated)}</span>` : '(missing)'}${n.stale ? ' · stale, 18+ months old' : ''}</dd>
        ${p ? `<dt>${p.kind === 'edge' ? 'Manager' : 'Rolls up to'}</dt><dd>${personLink(p.p)}</dd>` : ''}
        ${reports ? `<dt>Reports</dt><dd class="mono">${reports}</dd>` : ''}
      </dl>
      <section><h3 class="h3">Why</h3><p class="reason">${esc((n.reason || '–').replace(/C\d{4}-P\d{5}|U\d{5}/g, (id) => S.byId.get(id)?.name || id))}</p></section>
      ${cands ? `<section><h3 class="h3">Candidate managers</h3><ul class="cands">${cands}</ul></section>` : ''}
      ${truth}`;
  }
  function hideDetails() { $('#details').hidden = true; S.selected = null; }

  /* ---------- metrics ---------- */
  async function loadMetrics() {
    if (S.metrics) return;
    try {
      const [m, curves] = await Promise.all([api('/api/metrics'), api('/api/calibration')]);
      S.metrics = m; renderMetrics(m, curves);
    } catch (e) { $('#m-strip').innerHTML = `<p class="err">Could not load metrics: ${esc(e.message)}</p>`; }
  }
  function table(rows, cols) {
    return `<table class="tbl"><thead><tr>${cols.map((c) => `<th class="${c.num ? 'num' : ''}">${c.h}</th>`).join('')}</tr></thead><tbody>${rows.map((r) => `<tr class="${r._hl ? 'hl' : ''}">${cols.map((c) => `<td class="${c.num ? 'num' : ''}">${c.f ? c.f(r[c.k], r) : esc(r[c.k])}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
  }
  function renderMetrics(m, curves) {
    const t = m.test, op = m.operating_point;
    const strip = [
      ['Edge precision', pct(t.precision), `${t.wrong_edges} wrong of ${t.edges.toLocaleString()}`],
      ['Edge coverage', pct(t.coverage), 'people given a direct manager'],
      ['Edge or roll-up', pct(t.answered_any), `roll-up precision ${pct(t.rollup_precision)}`],
      ...(m.ic_identifiability ? [['IC ceiling', pct(m.ic_identifiability.by_team), 'ICs placeable even with perfect titles']] : []),
      ['Threshold', fmt(op.threshold), 'picked on train for 95% precision'],
      ['Guess everyone', pct(m.naive_always_guess_test.precision), 'precision with no abstaining'],
    ];
    $('#m-strip').innerHTML = strip.map(([k, v, s]) => `<div><dt>${k}</dt><dd>${v}<small>${s}</small></dd></div>`).join('');
    const ink = css('--ink'), muted = css('--muted'), line = css('--line'), accent = css('--accent'), c2 = css('--c1');
    Chart.defaults.font.family = 'IBM Plex Sans, sans-serif'; Chart.defaults.color = muted; Chart.defaults.borderColor = line;
    const pc = curves.precision_coverage.filter((r) => r.precision != null);
    const opPt = pc.reduce((b, r) => Math.abs(r.threshold - op.threshold) < Math.abs(b.threshold - op.threshold) ? r : b, pc[0]);
    Object.values(S.charts).forEach((c) => c.destroy());
    S.charts.pc = new Chart($('#ch-pc'), { type: 'scatter', data: { datasets: [
      { label: 'Threshold sweep', data: pc.map((r) => ({ x: r.coverage, y: r.precision, t: r.threshold })), showLine: true, borderColor: accent, backgroundColor: accent, pointRadius: 2, borderWidth: 2 },
      { label: `Operating point (${fmt(op.threshold)})`, data: [{ x: t.coverage, y: t.precision, t: op.threshold }], pointRadius: 6, backgroundColor: c2, borderColor: c2 },
    ] }, options: { maintainAspectRatio: false, scales: { x: { title: { display: true, text: 'Coverage (share of people given an edge)' }, min: 0, max: 1, ticks: { callback: (v) => pct(v, 0) } }, y: { title: { display: true, text: 'Precision' }, min: 0.4, max: 1, ticks: { callback: (v) => pct(v, 0) } } },
      plugins: { tooltip: { callbacks: { label: (c) => `threshold ${fmt(c.raw.t)} · precision ${pct(c.raw.y)} · coverage ${pct(c.raw.x)}` } }, legend: { labels: { boxWidth: 10 } } } } });
    const rel = curves.reliability, raw = curves.reliability_raw;
    S.charts.rel = new Chart($('#ch-rel'), { type: 'scatter', data: { datasets: [
      { label: 'Perfect calibration', data: [{ x: 0, y: 0 }, { x: 1, y: 1 }], showLine: true, borderColor: line, borderDash: [4, 4], pointRadius: 0 },
      { label: 'Before (raw score)', data: raw.map((r) => ({ x: r.mean_confidence, y: r.accuracy, n: r.n })), showLine: true, borderColor: c2, backgroundColor: c2, pointRadius: 3 },
      { label: 'After isotonic', data: rel.map((r) => ({ x: r.mean_confidence, y: r.accuracy, n: r.n })), showLine: true, borderColor: accent, backgroundColor: accent, pointRadius: 3, borderWidth: 2 },
    ] }, options: { maintainAspectRatio: false, scales: { x: { min: 0, max: 1, title: { display: true, text: 'Stated confidence' } }, y: { min: 0, max: 1, title: { display: true, text: 'Actually correct' } } },
      plugins: { tooltip: { callbacks: { label: (c) => c.raw.n ? `said ${fmt(c.raw.x)} · right ${pct(c.raw.y)} · n=${c.raw.n}` : '' } }, legend: { labels: { boxWidth: 10 } } } } });
    const abl = Object.entries(m.ablations || {}).map(([k, v]) => ({ name: k, ...v, _hl: k === 'full system' }));
    $('#m-abl').innerHTML = table(abl, [{ h: 'Variant', k: 'name' }, { h: 'Precision', k: 'precision', num: 1, f: (v) => pct(v) }, { h: 'Coverage', k: 'coverage', num: 1, f: (v) => pct(v) }, { h: '+ roll-ups', k: 'answered_any', num: 1, f: (v) => pct(v) }]);
    const sq = m.sales_questions;
    $('#m-sales').innerHTML = table([
      { q: 'Who runs department X?', p: sq.who_runs_dept.precision, c: sq.who_runs_dept.coverage },
      { q: 'Economic buyer above an IC (anyone VP+ in their real chain)', p: sq.economic_buyer_above_ic.precision_in_true_chain, c: sq.economic_buyer_above_ic.coverage },
      { q: '…and it is their nearest VP or exec', p: sq.economic_buyer_above_ic.precision_nearest_vp_or_exec, c: sq.economic_buyer_above_ic.coverage },
    ], [{ h: 'Question', k: 'q' }, { h: 'Precision', k: 'p', num: 1, f: (v) => pct(v) }, { h: 'Answered', k: 'c', num: 1, f: (v) => pct(v) }]);
    const pr = m.parser;
    $('#m-parser').innerHTML = table([
      { k: 'Level read correctly', v: pct(pr.level_accuracy) }, { k: 'Department correct (when read)', v: pct(pr.dept_accuracy_when_given) },
      { k: 'Titles left unread', v: pct(pr.unparsed_rate) }, { k: 'Held-out vocabulary left unread', v: pct(pr.heldout_unparsed_rate) },
    ], [{ h: 'Check', k: 'k' }, { h: 'Result', k: 'v', num: 1 }]);
    const cols = (key, f = (x) => x, label = key) => [{ h: label, k: key, f: (v) => esc(f(v)) }, { h: 'Precision', k: 'precision', num: 1, f: (v) => pct(v) }, { h: 'Coverage', k: 'coverage', num: 1, f: (v) => pct(v) }, { h: '+ roll-ups', k: 'answered_any', num: 1, f: (v) => pct(v) }];
    const order = ['clean', 'moderate', 'messy', 'very_messy'];
    $('#m-noise').innerHTML = table([...m.breakdowns.noise_level].sort((a, b) => order.indexOf(a.noise_level) - order.indexOf(b.noise_level)), cols('noise_level', (x) => x.replace('_', ' '), 'Noise'));
    const lv = ['CEO', 'Exec', 'VP', 'Director', 'Manager', 'IC'];
    $('#m-level').innerHTML = table(m.breakdowns.true_level.filter((r) => r.true_level > 0), cols('true_level', (x) => lv[x], 'Level'));
    const so = ['100-199', '200-499', '500-999', '1000+'];
    $('#m-size').innerHTML = table([...m.breakdowns.size_bucket].sort((a, b) => so.indexOf(a.size_bucket) - so.indexOf(b.size_bucket)), cols('size_bucket', (x) => x, 'Employees'));
  }

  /* ---------- upload ---------- */
  let file = null;
  function setFile(f) { file = f; $('#drop-msg').textContent = f ? `${f.name} · ${(f.size / 1024).toFixed(0)} KB` : 'Nothing selected yet'; $('#run-upload').disabled = !f; $('#upload-err').hidden = true; }
  async function runUpload() {
    const btn = $('#run-upload'); btn.disabled = true; btn.textContent = 'Inferring…';
    try {
      const fd = new FormData(); fd.append('file', file);
      const d = await api('/api/infer', { method: 'POST', body: fd });
      location.hash = '#explore'; route();   // show the canvas before laying out, so the initial view is sized correctly
      setPayload(d);
      document.querySelectorAll('#company-list button').forEach((b) => b.setAttribute('aria-current', 'false'));
      $('#export').onclick = (e) => { if (S.payload.company.company_id !== 'UPLOAD') return; e.preventDefault(); downloadUploadCsv(); };
    } catch (e) { const el = $('#upload-err'); el.textContent = e.message; el.hidden = false; }
    finally { btn.disabled = !file; btn.textContent = 'Infer the org chart'; }
  }
  function downloadUploadCsv() {
    const rows = [['person_id', 'name', 'title', 'level', 'department', 'manager_id', 'manager_name', 'confidence', 'rolls_up_to', 'reason']];
    for (const n of S.payload.nodes) {
      const p = parentOf(n); const m = p ? S.byId.get(p.p) : null;
      rows.push([n.id, n.name, n.title, n.level_name, n.dept, p?.kind === 'edge' ? p.p : '', p?.kind === 'edge' ? m?.name : '', p?.kind === 'edge' ? fmt(p.conf, 3) : '', p?.kind === 'rollup' ? m?.name : '', n.reason]);
    }
    const csv = rows.map((r) => r.map((v) => `"${String(v ?? '').replace(/"/g, '""')}"`).join(',')).join('\n');
    const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' })); a.download = 'inferred_org_chart.csv'; a.click();
  }

  /* ---------- picker drawer (mobile) ---------- */
  function openPicker() { $('#picker').classList.add('open'); $('#scrim').hidden = false; }
  function closePicker() { $('#picker').classList.remove('open'); $('#scrim').hidden = true; }

  /* ---------- wire up ---------- */
  function bind() {
    window.addEventListener('hashchange', route);
    $('#q').addEventListener('input', (e) => { clearTimeout(qTimer); qTimer = setTimeout(() => { S.q = e.target.value; S.page = 1; loadList(); }, 180); });
    $('#f-industry').addEventListener('change', (e) => { S.industry = e.target.value; S.page = 1; loadList(); });
    $('#f-size').addEventListener('change', (e) => { S.size = e.target.value; S.page = 1; loadList(); });
    $('#f-noise').addEventListener('change', (e) => { S.noise = e.target.value; S.page = 1; loadList(); });
    $('#prev').addEventListener('click', () => { S.page--; loadList(); });
    $('#next').addEventListener('click', () => { S.page++; loadList(); });
    $('#company-list').addEventListener('click', (e) => { const b = e.target.closest('button[data-id]'); if (b) location.hash = '#explore/' + b.dataset.id; });
    let raf;
    $('#thr').addEventListener('input', (e) => { S.thr = +e.target.value; $('#thr-out').textContent = fmt(S.thr); cancelAnimationFrame(raf); raf = requestAnimationFrame(() => draw(false)); });
    $('#thr').addEventListener('change', () => draw(false, true));   // refit once the slider is released
    $('#thr-reset').addEventListener('click', () => { S.thr = S.opThr; $('#thr').value = S.thr; $('#thr-out').textContent = fmt(S.thr); draw(false, true); });
    $('#t-rollup').addEventListener('change', (e) => { S.rollups = e.target.checked; draw(false, true); });
    $('#t-collapse').addEventListener('change', (e) => { S.collapse = e.target.checked; draw(false, true); });
    $('#t-unplaced').addEventListener('change', (e) => { S.unplaced = e.target.checked; draw(false, true); });
    $('#t-truth').addEventListener('change', (e) => { S.truth = e.target.checked; document.body.classList.toggle('truth', S.truth); draw(false); if (S.selected) showDetails(S.byId.get(S.selected)); });
    $('#f-dept').addEventListener('change', (e) => { S.dept = e.target.value; draw(false, true); });
    $('#fit').addEventListener('click', () => S.cy && readableView());
    $('#expand-all').addEventListener('click', () => {
      if (!S.payload) return;
      if (S.expandAll) { S.expandAll = false; S.open.clear(); S.expanded.clear(); draw(false, 'auto'); }
      else { S.expandAll = true; draw(false, 'fit'); }
    });
    S.viewReport = viewReport; S.readableView = readableView;
    S.fitLevels = () => { const keep = S.foldLevel, out = {}; for (const L of [2, 1, 0]) { S.foldLevel = L; layout(); const bb = shownBox(); out[L] = { fitZoom: +fitZoom().toFixed(3), w: Math.round(bb.w), h: Math.round(bb.h) }; } S.foldLevel = keep; draw(false, 'fit'); return out; };
    window.orgchart = S; // handy for debugging, screenshot scripts and scripts/check_view.py
    $('#d-close').addEventListener('click', () => { hideDetails(); clearDim(); });
    $('#d-body').addEventListener('click', (e) => { const b = e.target.closest('[data-focus]'); if (!b) return; const id = b.dataset.focus; revealPerson(id); focus(id); });
    $('#more-controls').addEventListener('click', (e) => { const open = $('#toolbar').classList.toggle('open'); e.currentTarget.setAttribute('aria-expanded', open); requestAnimationFrame(() => S.cy && S.cy.resize()); });
    $('#open-picker').addEventListener('click', openPicker);
    $('#scrim').addEventListener('click', closePicker);
    $('#theme').addEventListener('click', () => {
      const t = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
      document.documentElement.dataset.theme = t; localStorage.setItem('theme', t);
      if (S.cy) { S.cy.style(style()); draw(false); }
      if (S.metrics) { const m = S.metrics; S.metrics = null; loadMetrics(); }
    });
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape') { hideDetails(); clearDim(); closePicker(); } if (e.key === '/' && document.activeElement.tagName !== 'INPUT') { e.preventDefault(); openPicker(); $('#q').focus(); } });
    const drop = $('#drop');
    $('#file').addEventListener('change', (e) => setFile(e.target.files[0] || null));
    ['dragenter', 'dragover'].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add('over'); }));
    ['dragleave', 'drop'].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove('over'); }));
    drop.addEventListener('drop', (e) => setFile(e.dataTransfer.files[0] || null));
    $('#run-upload').addEventListener('click', runUpload);
  }

  async function start() {
    bind();
    await wake();
    await loadList();
    route();
    if (!/^#explore\/C\d{4}$/.test(location.hash) && (location.hash === '' || location.hash === '#explore')) {
      // open a held-out, moderately messy company of typical size as the first impression
      const d = await api('/api/companies?split=test&noise=moderate&size=200-499&page_size=1');
      if (d.items[0]) location.hash = '#explore/' + d.items[0].company_id;
    }
  }
  start();
})();
