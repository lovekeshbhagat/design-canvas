// design-canvas review: inspect any element on a screen, comment on it, send the review back as a file.
// No server: comments live in this browser until exported. Review text is always inserted as text, never HTML.
;(() => {
  const D = window.DC
  const C = window.DC_CANVAS
  if (!D || !C) return
  const { board, world } = C
  const drawer = document.getElementById('dc-drawer')
  const btnInspect = document.getElementById('dc-inspect')
  const btnComments = document.getElementById('dc-comments')
  const countEl = document.getElementById('dc-count')
  const KEY = 'design-canvas.review.' + D.app
  const STATUSES = ['open', 'resolved', 'wontfix', 'question', 'reopened']
  const OPEN = ['open', 'question', 'reopened']
  const CLOSED = ['resolved', 'wontfix']
  const ID = /^[a-z0-9][a-z0-9_-]{2,63}$/
  const TS = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z$/
  const PATH = /^[a-z][a-z0-9-]*:nth-of-type\(\d{1,4}\)(>[a-z][a-z0-9-]*:nth-of-type\(\d{1,4}\))*$/

  // ---------- helpers ----------
  function h(tag, attrs, ...kids) {
    const el = document.createElement(tag)
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v == null || v === false) continue
      if (k === 'class') el.className = v
      else if (k.startsWith('on')) el.addEventListener(k.slice(2), v)
      else el.setAttribute(k, v === true ? '' : v)
    }
    for (const kid of kids.flat(Infinity)) {
      if (kid == null || kid === false) continue
      el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)))
    }
    return el
  }
  const nowIso = () => new Date().toISOString().replace(/\.\d{3}Z$/, 'Z')
  const clip = (s, n) => String(s ?? '').replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f​-‏‪-‮⁦-⁩]/g, '').slice(0, n)
  const slug = (s) => (String(s || '').toLowerCase().normalize('NFKD').replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 24) || 'reviewer')
  const rand = () => Array.from(crypto.getRandomValues(new Uint8Array(5)), (b) => (b % 36).toString(36)).join('')
  const round = (n) => Math.round(n * 10) / 10
  const px = (n) => `${round(n)}`

  // ---------- comments: validation, storage, merge ----------
  function clean(c) {
    if (!c || typeof c !== 'object') return null
    const id = String(c.id || '').toLowerCase()
    if (!ID.test(id) || typeof c.screen !== 'string' || typeof c.body !== 'string' || !STATUSES.includes(c.status)) return null
    if (!TS.test(c.created || '') || !TS.test(c.modified || '')) return null
    const a = c.anchor && typeof c.anchor === 'object' ? c.anchor : {}
    const b = a.box && typeof a.box === 'object' ? a.box : null
    const tokens = {}
    if (c.tokens && typeof c.tokens === 'object') for (const [k, v] of Object.entries(c.tokens).slice(0, 20)) tokens[clip(k, 40)] = clip(v, 80)
    const reply = String(c.replyTo || '').toLowerCase()
    return {
      id, replyTo: ID.test(reply) ? reply : null, screen: clip(c.screen, 80), built: clip(c.built, 40),
      anchor: {
        dc: a.dc ? clip(a.dc, 120) : undefined,
        path: typeof a.path === 'string' && PATH.test(a.path) ? a.path.slice(0, 400) : undefined,
        component: a.component ? clip(a.component, 80) : undefined,
        text: a.text ? clip(a.text, 200) : undefined,
        box: b ? { x: +b.x || 0, y: +b.y || 0, w: +b.w || 0, h: +b.h || 0 } : undefined,
      },
      tokens, body: clip(c.body, 4000), author: clip(c.author, 80) || 'Reviewer', status: c.status,
      created: c.created, modified: c.modified, resolvedAt: TS.test(c.resolvedAt || '') ? c.resolvedAt : null,
      resolution: c.resolution ? clip(c.resolution, 1000) : undefined,
    }
  }
  function load() {
    try {
      const v = JSON.parse(localStorage.getItem(KEY) || '{}')
      return v && typeof v === 'object' ? v : {}
    } catch {
      return {}
    }
  }
  const local = load()
  local.author = clip(local.author, 80)
  local.comments = (Array.isArray(local.comments) ? local.comments : []).map(clean).filter(Boolean)
  let imported = []
  function save() {
    try {
      localStorage.setItem(KEY, JSON.stringify({ author: local.author, comments: local.comments, lastExport: local.lastExport }))
    } catch {}
  }
  // Same rule as engine/reviews.py: newest `modified` wins, but a closed comment is only reopened explicitly.
  function newer(cur, nw) {
    if (CLOSED.includes(cur.status) && !['reopened', ...CLOSED].includes(nw.status)) return cur
    return nw.modified > cur.modified ? nw : cur
  }
  function all() {
    const m = new Map()
    for (const src of [D.comments || [], imported, local.comments]) {
      for (const raw of src) {
        const c = clean(raw)
        if (!c) continue
        const cur = m.get(c.id)
        m.set(c.id, cur ? newer(cur, c) : c)
      }
    }
    return [...m.values()].sort((a, b) => (a.created < b.created ? -1 : a.created > b.created ? 1 : a.id < b.id ? -1 : 1))
  }
  const topLevel = () => all().filter((c) => !c.replyTo)
  const pinNumber = (id) => topLevel().findIndex((c) => c.id === id) + 1

  // ---------- the cascade, from the app's own CSS text (engine/build.py parse_css) ----------
  const cmp = (x, y) => {
    for (let i = 0; i < Math.max(x.length, y.length); i++) {
      const d = (x[i] || 0) - (y[i] || 0)
      if (d) return d
    }
    return 0
  }
  function splitList(sel) {
    const out = []
    let depth = 0, cur = ''
    for (const ch of sel) {
      if (ch === '(' || ch === '[') depth++
      else if (ch === ')' || ch === ']') depth--
      if (ch === ',' && !depth) { out.push(cur.trim()); cur = '' } else cur += ch
    }
    if (cur.trim()) out.push(cur.trim())
    return out
  }
  function specificity(sel) {
    let s = sel.replace(/:where\((?:[^()]|\([^()]*\))*\)/g, ' ').replace(/:(?:is|not|has)\(((?:[^()]|\([^()]*\))*)\)/g, ' $1')
    let a = 0, b = 0, c = 0
    s = s.replace(/\[[^\]]*\]/g, () => { b++; return ' ' })
    s = s.replace(/#[\w-]+/g, () => { a++; return ' ' })
    s = s.replace(/\.[\w-]+/g, () => { b++; return ' ' })
    s = s.replace(/::[\w-]+(\([^)]*\))?/g, () => { c++; return ' ' })
    s = s.replace(/:[\w-]+(\([^)]*\))?/g, () => { b++; return ' ' })
    s.replace(/(^|[\s>+~])([a-zA-Z][\w-]*)/g, () => { c++ })
    return [a, b, c]
  }
  const RULES = (D.rules || []).map((r, i) => ({ i, m: r.m, d: r.d, parts: splitList(r.s).map((s) => ({ s, spec: specificity(s) })) }))
  const mqs = {}
  const mq = (m) => !m || (mqs[m] = mqs[m] || matchMedia(m)).matches
  function declsOn(el) {
    const out = []
    for (const r of RULES) {
      if (r.m && !mq(r.m)) continue
      let best = null
      for (const p of r.parts) {
        let ok = false
        try { ok = el.matches(p.s) } catch {}
        if (ok && (!best || cmp(p.spec, best) > 0)) best = p.spec
      }
      if (best) for (const [prop, value, imp] of r.d) out.push({ prop, value, rank: [imp ? 1 : 0, 0, ...best, r.i], where: r.parts.map((p) => p.s).join(', ') })
    }
    const inline = el.getAttribute('style')
    if (inline) {
      for (const part of inline.split(/;(?![^(]*\))/)) {
        const k = part.indexOf(':')
        if (k < 0) continue
        let v = part.slice(k + 1).trim()
        const imp = /!important$/.test(v)
        if (imp) v = v.replace(/!important$/, '').trim()
        out.push({ prop: part.slice(0, k).trim().toLowerCase(), value: v, rank: [imp ? 1 : 0, 1, 0, 0, 0, 1e9], where: 'inline style' })
      }
    }
    return out
  }
  const GROUPS = [
    { key: 'color', label: 'Text colour', kind: 'color', inherit: true, props: ['color'] },
    { key: 'background', label: 'Background', kind: 'color', props: ['background', 'background-color'] },
    { key: 'border', label: 'Border', kind: 'color', props: ['border', 'border-color', 'border-top', 'border-right', 'border-bottom', 'border-left'] },
    { key: 'font', label: 'Type', kind: 'type', inherit: true, props: ['font', 'font-family', 'font-size', 'line-height', 'font-weight', 'font-style'] },
    { key: 'letter', label: 'Letter spacing', kind: 'size', inherit: true, props: ['letter-spacing'] },
    { key: 'padding', label: 'Padding', kind: 'size', props: ['padding', 'padding-inline', 'padding-block', 'padding-top', 'padding-right', 'padding-bottom', 'padding-left'] },
    { key: 'margin', label: 'Margin', kind: 'size', props: ['margin', 'margin-inline', 'margin-block', 'margin-top', 'margin-right', 'margin-bottom', 'margin-left'] },
    { key: 'gap', label: 'Gap', kind: 'size', props: ['gap', 'row-gap', 'column-gap'] },
    { key: 'radius', label: 'Corner radius', kind: 'size', props: ['border-radius'] },
    { key: 'shadow', label: 'Shadow', kind: 'shadow', props: ['box-shadow'] },
  ]
  function authored(el, group, stop) {
    for (let n = el; n; n = n.parentElement) {
      const decls = declsOn(n)
      const wins = []
      for (const p of group.props) {
        let w = null
        for (const d of decls) if (d.prop === p && (!w || cmp(d.rank, w.rank) >= 0)) w = d
        if (w) wins.push(w)
      }
      if (wins.length) return { wins: wins.sort((a, b) => cmp(a.rank, b.rank)), from: n === el ? null : n }
      if (!group.inherit || n === stop) return null
    }
    return null
  }
  function tokenOf(v) {
    const t = D.vars[v]
    if (!t) return { name: v, unknown: true }
    if (t.startsWith('roles.')) {
      const role = t.slice(6)
      return D.roles[role] ? { name: `colors.${D.roles[role]}`, via: `role ${role}` } : { name: t }
    }
    return { name: t }
  }
  function describe(value, kind) {
    const re = /var\(\s*(--[\w-]+)\s*(?:,[^)]*)?\)/g
    const toks = []
    let m
    while ((m = re.exec(value))) toks.push(tokenOf(m[1]))
    const rest = value.replace(re, ' ')
    const raw = []
    if (kind !== 'size' && kind !== 'type') raw.push(...(rest.match(/#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\)|hsla?\([^)]*\)/g) || []))
    if (kind === 'size' || kind === 'type') raw.push(...(rest.match(/-?\d*\.?\d+px/g) || []).filter((x) => parseFloat(x) !== 0))
    if (kind === 'shadow') raw.push(...(rest.match(/#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\)/g) || []))
    return { toks, raw }
  }
  const rgbOf = (s) => (String(s).match(/[\d.]+/g) || []).map(Number)
  // A hand-typed size that equals a token: name the token the designer probably meant.
  function sameAs(raw, key) {
    const n = parseFloat(raw)
    if (!/px$/.test(raw) || isNaN(n)) return ''
    const pool = key === 'radius' ? D.radii : key === 'font' ? {} : D.spacing
    const hit = Object.entries(pool || {}).find(([, v]) => v === n)
    return hit ? ` = ${key === 'radius' ? 'radii' : 'spacing'}.${hit[0]}` : ''
  }
  function colorNames(computed, theme) {
    const [r, g, b, a = 1] = rgbOf(computed)
    if (r == null || a === 0) return []
    const out = []
    for (const [k, v] of Object.entries(D.colors[theme] || {})) if (Math.abs(v[0] - r) <= 1 && Math.abs(v[1] - g) <= 1 && Math.abs(v[2] - b) <= 1 && Math.abs((v[3] ?? 1) - a) < 0.02) out.push(`colors.${k}`)
    return out
  }
  function typeNames(cs) {
    const size = parseFloat(cs.fontSize), lh = parseFloat(cs.lineHeight)
    return Object.entries(D.type || {}).filter(([, t]) => t.size === size && (isNaN(lh) || Math.abs(t.lh - lh) < 0.6)).map(([k, t]) => ({ name: `type.${k}`, weightDiff: String(t.weight) !== String(cs.fontWeight) }))
  }
  const themeOf = (el) => el.closest('[data-theme]')?.dataset.theme || D.defaultTheme
  const describeEl = (n) => n.tagName.toLowerCase() + (n.dataset?.dc ? `[data-dc=${n.dataset.dc}]` : '') + [...n.classList].slice(0, 3).map((c) => '.' + c).join('')
  function componentOf(el) {
    for (let n = el; n && !n.classList.contains('sc'); n = n.parentElement) {
      const c = [...n.classList].find((x) => x.startsWith('p-'))
      if (c) return c
    }
    return undefined
  }
  function inspect(el) {
    const sc = el.closest('.sc'), dev = el.closest('.dev')
    const cs = getComputedStyle(el)
    const k = dev.getBoundingClientRect().width / dev.offsetWidth || 1
    const r = el.getBoundingClientRect()
    const theme = themeOf(el)
    const rows = []
    const flags = []
    for (const g of GROUPS) {
      const a = authored(el, g, sc)
      const row = { g, tokens: [], raw: [], from: a?.from, notes: [] }
      if (a) {
        for (const w of a.wins) {
          const d = describe(w.value, g.kind)
          row.tokens.push(...d.toks)
          row.raw.push(...d.raw.map((x) => `${x}${sameAs(x, g.key)} (${w.prop})`))
          if (w.prop !== g.props[0] && a.wins[0].prop === g.props[0]) row.notes.push(`${w.prop}: ${w.value}`)
        }
      }
      if (g.key === 'color') row.value = cs.color
      if (g.key === 'background') row.value = cs.backgroundColor
      if (g.key === 'font') row.value = `${cs.fontSize}/${cs.lineHeight} · ${cs.fontWeight} · ${cs.fontFamily.split(',')[0].replace(/["']/g, '')}`
      if (g.key === 'letter') row.value = cs.letterSpacing
      if (g.key === 'padding') row.value = [cs.paddingTop, cs.paddingRight, cs.paddingBottom, cs.paddingLeft].join(' ')
      if (g.key === 'margin') row.value = [cs.marginTop, cs.marginRight, cs.marginBottom, cs.marginLeft].join(' ')
      if (g.key === 'gap') row.value = cs.display.includes('flex') || cs.display.includes('grid') ? cs.gap : ''
      if (g.key === 'radius') row.value = cs.borderRadius
      if (g.key === 'shadow') row.value = cs.boxShadow === 'none' ? '' : cs.boxShadow
      if (!a) {
        // Nothing written for it: name it from the computed value when that is a token value.
        if (g.key === 'color') row.guess = colorNames(cs.color, theme)
        if (g.key === 'background') row.guess = colorNames(cs.backgroundColor, theme)
        if (g.key === 'font') row.guess = typeNames(cs).map((t) => t.name + (t.weightDiff ? ` (weight ${cs.fontWeight})` : ''))
      }
      const trivial = !row.value || /^(0px( 0px)*|none|normal|rgba\(0, 0, 0, 0\))$/.test(row.value)
      const empty = !row.tokens.length && !row.raw.length && !row.guess?.length && trivial
      if (!empty) rows.push(row)
      if (row.raw.length) flags.push(`${g.label}: ${row.raw.join(', ')}`)
    }
    return { el, theme, w: round(r.width / k), h: round(r.height / k), rows, flags, component: componentOf(el), text: (el.textContent || '').replace(/\s+/g, ' ').trim() }
  }

  // ---------- anchors ----------
  function cssPath(el, base) {
    const parts = []
    for (let n = el; n && n !== base; n = n.parentElement) {
      let i = 1
      for (let s = n.previousElementSibling; s; s = s.previousElementSibling) if (s.tagName === n.tagName) i++
      parts.unshift(`${n.tagName.toLowerCase()}:nth-of-type(${i})`)
    }
    return parts.join('>')
  }
  function anchorOf(el) {
    const dev = el.closest('.dev'), sc = el.closest('.sc')
    const dcEl = el.closest('[data-dc]')
    const base = dcEl && sc.contains(dcEl) ? dcEl : sc
    const k = dev.getBoundingClientRect().width / dev.offsetWidth || 1
    const r = el.getBoundingClientRect(), d = dev.getBoundingClientRect()
    const path = el === base ? '' : cssPath(el, base)
    return {
      dc: base !== sc ? base.dataset.dc : undefined, path: path || undefined, component: componentOf(el),
      text: (el.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 120) || undefined,
      box: { x: round((r.left - d.left) / k), y: round((r.top - d.top) / k), w: round(r.width / k), h: round(r.height / k) },
    }
  }
  function findAnchor(c) {
    const fig = world.querySelector(`.cv-frame[data-id="${CSS.escape(c.screen)}"]`)
    if (!fig) return null
    const dev = fig.querySelector('.dev'), sc = dev.querySelector('.sc')
    const a = c.anchor || {}
    let base = sc
    if (a.dc) base = dev.querySelector(`[data-dc="${CSS.escape(a.dc)}"]`) || sc
    let el = null
    if (a.path && (base !== sc || !a.dc)) { try { el = base.querySelector(':scope>' + a.path) } catch {} }
    else if (a.dc && base !== sc) el = base
    const txt = (n) => (n.textContent || '').replace(/\s+/g, ' ').trim()
    if (el && a.text && !txt(el).startsWith(a.text.slice(0, 40))) el = null
    if (!el && a.text) {
      const pool = a.component ? dev.querySelectorAll(`.${CSS.escape(a.component)}, .${CSS.escape(a.component)} *`) : sc.querySelectorAll('*')
      for (const n of pool) if (txt(n) === a.text) el = n // keep the deepest match
    }
    return { fig, dev, el, box: a.box }
  }

  // ---------- hover + selection overlays ----------
  const hover = h('div', { class: 'dc-hover dc-ui', hidden: true }, h('span', { class: 'dc-size' }))
  const selBox = h('div', { class: 'dc-sel dc-ui', hidden: true })
  board.append(hover, selBox)
  let selected = null
  let tab = 'inspect'
  let filter = 'open'
  let focusId = null
  function place(box, el) {
    if (!el || !el.isConnected || el.closest('.cv-page')?.hidden) { box.hidden = true; return }
    const b = board.getBoundingClientRect(), r = el.getBoundingClientRect()
    Object.assign(box.style, { left: `${r.left - b.left}px`, top: `${r.top - b.top}px`, width: `${r.width}px`, height: `${r.height}px` })
    box.hidden = false
  }
  function pickable(t) {
    if (!t || t.closest('.dc-ui, .dc-pin')) return null
    if (t.closest('svg') && t.closest('svg') !== t) t = t.closest('svg')
    const sc = t.closest('.dev .sc')
    return sc && t !== sc ? t : null
  }
  let raf = 0
  board.addEventListener('pointermove', (e) => {
    if (!C.inspecting() || e.buttons) { hover.hidden = true; return }
    cancelAnimationFrame(raf)
    raf = requestAnimationFrame(() => {
      const el = pickable(document.elementFromPoint(e.clientX, e.clientY))
      if (!el) { hover.hidden = true; return }
      place(hover, el)
      const dev = el.closest('.dev')
      const k = dev.getBoundingClientRect().width / dev.offsetWidth || 1
      const r = el.getBoundingClientRect()
      hover.firstChild.textContent = `${px(r.width / k)} × ${px(r.height / k)}`
    })
  })
  board.addEventListener('pointerleave', () => { hover.hidden = true })

  // ---------- drawer ----------
  function setInspect(on) {
    document.body.classList.toggle('dc-inspecting', on)
    btnInspect.setAttribute('aria-pressed', String(on))
    hover.hidden = true
    if (on) openDrawer('inspect')
  }
  function openDrawer(t) {
    tab = t
    drawer.hidden = false
    render()
  }
  function closeDrawer() {
    drawer.hidden = true
    setInspect(false)
    select(null)
  }
  function select(el) {
    selected = el
    place(selBox, el)
    if (el) openDrawer('inspect')
    else if (!drawer.hidden) render()
  }
  function chip(t) {
    return h('span', { class: `dc-tok${t.unknown ? ' unknown' : ''}`, title: t.via ? `through ${t.via}` : null }, t.name, t.via ? h('small', {}, ` · ${t.via}`) : null)
  }
  function inspectView() {
    if (!selected || !selected.isConnected) {
      return h('div', { class: 'dc-empty' },
        C.inspecting()
          ? h('p', {}, 'Click anything on a screen to see its size and the design tokens it uses.')
          : h('p', {}, 'Turn on ', h('b', {}, 'Inspect'), ' and click anything on a screen to see its size and the design tokens it uses.'),
        h('p', { class: 'dc-muted' }, 'Tip: press I to switch Inspect on and off, C for comments.'))
    }
    const info = inspect(selected)
    const fig = selected.closest('.cv-frame')
    const scr = D.screens[fig.dataset.id] || {}
    const here = all().filter((c) => c.screen === fig.dataset.id && findAnchor(c)?.el === selected)
    return h('div', { class: 'dc-inspect' },
      h('div', { class: 'dc-head' },
        h('code', { class: 'dc-el' }, describeEl(selected)),
        h('div', { class: 'dc-muted' }, `${scr.title || fig.dataset.id} · ${scr.state || ''}`),
        scr.source ? h('code', { class: 'dc-src' }, scr.source) : null,
        info.component ? h('div', {}, 'Component ', h('span', { class: 'dc-tok' }, info.component)) : null),
      h('dl', { class: 'dc-rows' },
        h('dt', {}, 'Size'), h('dd', {}, `${px(info.w)} × ${px(info.h)}`),
        info.rows.map((r) => [
          h('dt', {}, r.g.label),
          h('dd', {},
            r.tokens.length ? h('div', { class: 'dc-toks' }, r.tokens.map(chip)) : null,
            !r.tokens.length && r.guess?.length ? h('div', { class: 'dc-toks' }, r.guess.map((n) => h('span', { class: 'dc-tok guess', title: 'matched by value' }, n)), h('small', { class: 'dc-muted' }, ' by value')) : null,
            r.raw.length ? h('div', { class: 'dc-off' }, 'Off-system: ', r.raw.join(', ')) : null,
            r.notes.length ? h('div', { class: 'dc-muted' }, 'Overridden: ', r.notes.join('; ')) : null,
            r.value ? h('div', { class: 'dc-val' }, r.value) : null,
            r.from ? h('div', { class: 'dc-muted' }, 'inherited from ', h('code', {}, describeEl(r.from))) : null),
        ]),
        info.text ? [h('dt', {}, 'Text'), h('dd', { class: 'dc-quote' }, info.text.slice(0, 120))] : null),
      info.flags.length ? h('p', { class: 'dc-off-note' }, `${info.flags.length} value${info.flags.length > 1 ? 's are' : ' is'} typed by hand instead of using a token.`) : null,
      here.length ? h('div', { class: 'dc-here' }, h('h4', {}, 'Comments here'), here.map((c) => commentCard(c, true))) : null,
      composer((body) => addComment(selected, body, null)))
  }
  function composer(onSave, label = 'Add comment', placeholder = 'What should change? Be specific: "make this 16 not 14", "use the accent colour"…') {
    const name = h('input', { class: 'dc-name', type: 'text', maxlength: '80', placeholder: 'Your name', value: local.author || '', 'aria-label': 'Your name' })
    const box = h('textarea', { class: 'dc-text', rows: '3', maxlength: '4000', placeholder, 'aria-label': 'Comment' })
    const go = h('button', {
      type: 'button', class: 'dc-btn primary',
      onclick: () => {
        const author = clip(name.value.trim(), 80)
        const body = clip(box.value.trim(), 4000)
        if (!author) { name.focus(); return }
        if (!body) { box.focus(); return }
        local.author = author
        onSave(body)
      },
    }, label)
    return h('div', { class: 'dc-compose' }, local.author ? null : name, box, go, local.author ? h('button', { type: 'button', class: 'dc-link', onclick: () => { local.author = ''; save(); render() } }, `Commenting as ${local.author} · change`) : null)
  }
  function commentCard(c, compact) {
    const n = c.replyTo ? null : pinNumber(c.id)
    const replies = compact ? [] : all().filter((x) => x.replyTo === c.id)
    const scr = D.screens[c.screen]
    const isOpen = OPEN.includes(c.status)
    let replying = null
    const card = h('article', { class: `dc-card${focusId === c.id ? ' focus' : ''}`, 'data-id': c.id },
      h('header', {},
        n ? h('span', { class: `dc-num ${isOpen ? 'is-open' : 'is-closed'}` }, String(n)) : null,
        h('b', {}, c.author), h('span', { class: 'dc-muted' }, ` · ${c.created.slice(0, 10)}`),
        h('span', { class: `dc-status s-${c.status}` }, c.status)),
      compact ? null : h('div', { class: 'dc-muted dc-where' }, scr ? scr.title : `${c.screen} (screen not on the canvas)`, c.anchor?.text ? ` · “${c.anchor.text.slice(0, 50)}”` : ''),
      h('p', { class: 'dc-body' }, c.body),
      c.resolution ? h('p', { class: 'dc-resolution' }, h('b', {}, 'Resolution: '), c.resolution) : null,
      h('div', { class: 'dc-actions' },
        compact ? null : h('button', { type: 'button', class: 'dc-link', onclick: () => show(c) }, 'Show'),
        isOpen
          ? h('button', { type: 'button', class: 'dc-link', onclick: () => setStatus(c, 'resolved') }, 'Resolve')
          : h('button', { type: 'button', class: 'dc-link', onclick: () => setStatus(c, 'reopened') }, 'Reopen'),
        c.replyTo ? null : h('button', { type: 'button', class: 'dc-link', onclick: () => { replying.hidden = !replying.hidden } }, 'Reply')),
      (replying = h('div', { class: 'dc-reply', hidden: true }, composer((body) => addReply(c, body), 'Reply', 'Reply…'))),
      replies.length ? h('div', { class: 'dc-replies' }, replies.map((r) => commentCard(r, true))) : null)
    return card
  }
  function commentsView() {
    const list = topLevel().filter((c) => filter === 'all' || OPEN.includes(c.status))
    const file = h('input', { type: 'file', accept: 'application/json,.json', hidden: true, onchange: (e) => openFile(e.target.files[0]) })
    const mine = local.comments.length
    return h('div', { class: 'dc-comments' },
      h('div', { class: 'dc-filter', role: 'group', 'aria-label': 'Filter' },
        h('button', { type: 'button', class: filter === 'open' ? 'on' : '', onclick: () => { filter = 'open'; render() } }, 'Open'),
        h('button', { type: 'button', class: filter === 'all' ? 'on' : '', onclick: () => { filter = 'all'; render() } }, 'All')),
      list.length ? list.map((c) => commentCard(c, false)) : h('p', { class: 'dc-empty' }, filter === 'open' ? 'No open comments.' : 'No comments yet. Turn on Inspect, click an element and add one.'),
      imported.length ? h('p', { class: 'dc-muted' }, `Showing ${imported.length} comment(s) from an opened file (not saved).`) : null,
      h('footer', { class: 'dc-foot' },
        h('button', { type: 'button', class: 'dc-btn primary', disabled: !mine, onclick: () => { exportReview(true) } }, `Send review${mine ? ` (${mine})` : ''}`),
        h('button', { type: 'button', class: 'dc-btn', onclick: () => file.click() }, 'Open review file'),
        file,
        h('p', { class: 'dc-muted' }, 'Comments stay in this browser until you send the review file to the developer.')))
  }
  function render() {
    if (drawer.hidden) return
    const open = topLevel().filter((c) => OPEN.includes(c.status)).length
    drawer.replaceChildren(
      h('div', { class: 'dc-tabs', role: 'tablist' },
        h('button', { type: 'button', role: 'tab', 'aria-selected': String(tab === 'inspect'), onclick: () => { tab = 'inspect'; render() } }, 'Inspect'),
        h('button', { type: 'button', role: 'tab', 'aria-selected': String(tab === 'comments'), onclick: () => { tab = 'comments'; render() } }, `Comments (${open})`),
        h('button', { type: 'button', class: 'dc-close', 'aria-label': 'Close', onclick: closeDrawer }, '×')),
      h('div', { class: 'dc-scroll' }, tab === 'inspect' ? inspectView() : commentsView()))
    if (focusId) drawer.querySelector(`.dc-card[data-id="${CSS.escape(focusId)}"]`)?.scrollIntoView({ block: 'nearest' })
  }
  function refresh() {
    countEl.textContent = String(topLevel().filter((c) => OPEN.includes(c.status)).length)
    drawPins()
    render()
  }

  // ---------- actions ----------
  function addComment(el, body, replyTo) {
    const t = nowIso()
    const info = inspect(el)
    const tokens = {}
    for (const r of info.rows) {
      const name = r.tokens[0]?.name || r.guess?.[0]
      if (name && !r.tokens[0]?.unknown) tokens[r.g.key] = name
    }
    local.comments.push({
      id: `${slug(local.author)}-${rand()}`, replyTo, screen: el.closest('.cv-frame').dataset.id, built: D.built,
      anchor: anchorOf(el), tokens, body, author: local.author, status: 'open', created: t, modified: t, resolvedAt: null,
    })
    save()
    refresh()
  }
  function addReply(parent, body) {
    const t = nowIso()
    local.comments.push({ id: `${slug(local.author)}-${rand()}`, replyTo: parent.id, screen: parent.screen, built: D.built, anchor: parent.anchor, tokens: {}, body, author: local.author, status: 'open', created: t, modified: t, resolvedAt: null })
    save()
    refresh()
  }
  function setStatus(c, status) {
    const t = nowIso()
    const copy = { ...c, status, modified: t, resolvedAt: CLOSED.includes(status) ? t : null }
    const i = local.comments.findIndex((x) => x.id === c.id)
    if (i >= 0) local.comments[i] = copy
    else local.comments.push(copy)
    save()
    refresh()
  }
  function show(c) {
    const scr = D.screens[c.screen]
    if (scr && scr.page !== C.current) C.showPage(scr.page, true)
    requestAnimationFrame(() => {
      const f = findAnchor(c)
      if (!f) return
      C.zoomToFrame(f.fig)
      focusId = c.id
      if (f.el) { selected = f.el; requestAnimationFrame(() => place(selBox, f.el)) }
      render()
    })
  }
  function reviewDoc() {
    return { format: 'design-canvas-review', schemaVersion: 1, app: D.app, exported: nowIso(), author: local.author || 'Reviewer', comments: local.comments.map(clean).filter(Boolean) }
  }
  function exportReview(download) {
    const doc = reviewDoc()
    if (!doc.comments.length) return doc
    if (download) {
      const url = URL.createObjectURL(new Blob([JSON.stringify(doc, null, 2) + '\n'], { type: 'application/json' }))
      const a = h('a', { href: url, download: `review-${slug(D.app)}-${doc.exported.slice(0, 10)}-${slug(doc.author)}.json` })
      document.body.append(a)
      a.click()
      a.remove()
      setTimeout(() => URL.revokeObjectURL(url), 2000)
      local.lastExport = doc.exported
      save()
    }
    return doc
  }
  function openFile(f) {
    if (!f) return
    if (f.size > 1_000_000) { alert('That file is over 1 MB, so it was not opened.'); return }
    const reader = new FileReader()
    reader.onload = () => {
      let doc
      try { doc = JSON.parse(String(reader.result)) } catch { alert('That file is not valid JSON.'); return }
      if (!doc || doc.format !== 'design-canvas-review' || doc.schemaVersion !== 1 || !Array.isArray(doc.comments) || doc.comments.length > 500) {
        alert('That is not a design-canvas review file.')
        return
      }
      imported = doc.comments.map(clean).filter(Boolean)
      tab = 'comments'
      filter = 'all'
      refresh()
    }
    reader.readAsText(f)
  }

  // ---------- pins ----------
  function drawPins() {
    world.querySelectorAll('.dc-pin').forEach((p) => p.remove())
    topLevel().forEach((c, i) => {
      const f = findAnchor(c)
      if (!f || f.fig.closest('.cv-page')?.hidden) return
      const k = f.dev.getBoundingClientRect().width / f.dev.offsetWidth || 1
      let x = 12, y = 12
      if (f.el) {
        const r = f.el.getBoundingClientRect(), d = f.dev.getBoundingClientRect()
        x = (r.right - d.left) / k
        y = (r.top - d.top) / k
      } else if (f.box) {
        x = f.box.x + f.box.w
        y = f.box.y
      }
      const isOpen = OPEN.includes(c.status)
      const pin = h('button', {
        type: 'button', class: `dc-pin ${isOpen ? 'is-open' : 'is-closed'}${f.el ? '' : ' is-detached'}`, 'data-id': c.id,
        title: `${c.author}: ${c.body.slice(0, 80)}${f.el ? '' : ' (element moved; shown at its old place)'}`,
      }, String(i + 1))
      pin.style.left = `${Math.min(Math.max(x, 12), f.dev.offsetWidth - 12)}px`
      pin.style.top = `${Math.min(Math.max(y, 12), f.dev.offsetHeight - 12)}px`
      f.dev.append(pin)
    })
    scalePins()
  }
  const scalePins = () => world.style.setProperty('--dc-pin-scale', String(Math.min(5, Math.max(0.6, 1 / C.view.k))))

  // ---------- wiring ----------
  btnInspect.addEventListener('click', () => setInspect(!C.inspecting()))
  btnComments.addEventListener('click', () => (drawer.hidden || tab !== 'comments' ? openDrawer('comments') : closeDrawer()))
  addEventListener('dc:pick', (e) => {
    const el = pickable(e.detail.target)
    select(el)
  })
  addEventListener('dc:pin', (e) => {
    const c = all().find((x) => x.id === e.detail.id)
    if (!c) return
    focusId = c.id
    openDrawer('comments')
    const f = findAnchor(c)
    if (f?.el) { selected = f.el; place(selBox, f.el) }
  })
  addEventListener('dc:view', () => {
    scalePins()
    if (selected) place(selBox, selected)
    hover.hidden = true
  })
  addEventListener('dc:page', () => {
    if (selected?.closest('.cv-page')?.hidden) select(null)
    drawPins()
  })
  document.addEventListener('keydown', (e) => {
    if (e.target.closest('input, textarea, select, [contenteditable]') || e.metaKey || e.ctrlKey || e.altKey) return
    if (e.key === 'i' || e.key === 'I') setInspect(!C.inspecting())
    else if (e.key === 'c' || e.key === 'C') btnComments.click()
    else if (e.key === 'Escape') {
      if (selected) select(null)
      else if (!drawer.hidden) closeDrawer()
    }
  })
  addEventListener('storage', (e) => {
    if (e.key !== KEY) return
    const v = load()
    local.author = clip(v.author, 80)
    local.comments = (Array.isArray(v.comments) ? v.comments : []).map(clean).filter(Boolean)
    refresh()
  })
  window.DC_REVIEW = { all, inspect, reviewDoc, select, findAnchor }
  refresh()
  document.fonts?.ready.then(drawPins)
})()
