// design-canvas inspect: work out which design tokens an element on a screen uses, and anchor comments to elements.
// Reads the app's own CSS rules (embedded by engine/build.py), so values written with var() keep their token names.
;(() => {
  const D = window.DC
  if (!D) return
  const round = (n) => Math.round(n * 10) / 10

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
    const fig = document.getElementById('world').querySelector(`.cv-frame[data-id="${CSS.escape(c.screen)}"]`)
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

  function pickable(t) {
    if (!t || t.closest('.dc-ui, .dc-pin')) return null
    if (t.closest('svg') && t.closest('svg') !== t) t = t.closest('svg')
    const sc = t.closest('.dev .sc')
    return sc && t !== sc ? t : null
  }

  window.DC_INSPECT = { inspect, anchorOf, findAnchor, componentOf, describeEl, pickable, themeOf }
})()
