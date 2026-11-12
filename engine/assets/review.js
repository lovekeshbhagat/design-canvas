// design-canvas review: comments on screens, their status, and sending them with git.
// Two modes:
//   helper  opened from `build.py --serve` (window.DC_SERVE): your comments save to your own review file,
//           End review commits and pushes it, Get latest pulls.
//   file    opened as a plain file: comments stay in this browser until you download the review file.
// Everything people wrote is inserted as text, never as HTML.
;(() => {
  const D = window.DC
  const C = window.DC_CANVAS
  const I = window.DC_INSPECT
  const S = window.DC_SERVE || null
  if (!D || !C || !I) return
  const { board, world } = C
  const drawer = document.getElementById('dc-drawer')
  const btnInspect = document.getElementById('dc-inspect')
  const btnComments = document.getElementById('dc-comments')
  const countEl = document.getElementById('dc-count')
  const STATUS = {
    open: { label: 'Needs fix', group: 'fix', mark: '' },
    ready: { label: 'Fix ready', group: 'check', mark: '✓' },
    question: { label: 'Question', group: 'check', mark: '?' },
    resolved: { label: 'Resolved', group: 'closed', mark: '✓' },
    wontfix: { label: "Won't fix", group: 'closed', mark: '–' },
  }
  const UPDATE_STATUSES = [...Object.keys(STATUS), 'deleted']
  const VIA = ['browser', 'cli', 'mcp', 'file']
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
  const clip = (s, n) => String(s ?? '').replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f\u200b-\u200f\u202a-\u202e\u2066-\u2069]/g, '').slice(0, n)
  const slug = (s) => String(s || '').toLowerCase().normalize('NFKD').replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 40) || 'reviewer'
  const rand = () => Array.from(crypto.getRandomValues(new Uint8Array(6)), (b) => (b % 36).toString(36)).join('')
  const byTime = (a, b) => (a < b ? -1 : a > b ? 1 : 0)
  function ago(ts) {
    const s = (Date.now() - Date.parse(ts)) / 1000
    if (!(s >= 0)) return ts.slice(0, 10)
    if (s < 60) return 'just now'
    if (s < 3600) return `${Math.floor(s / 60)} min ago`
    if (s < 86400) return `${Math.floor(s / 3600)} h ago`
    if (s < 86400 * 7) return `${Math.floor(s / 86400)} d ago`
    return ts.slice(0, 10)
  }
  const initials = (name) => (String(name).trim().split(/\s+/).map((w) => w[0]).join('').slice(0, 2) || '?').toUpperCase()
  const hue = (name) => [...String(name)].reduce((a, ch) => (a * 31 + ch.charCodeAt(0)) % 360, 7)
  const avatar = (name) => h('span', { class: 'dc-avatar', style: `background:hsl(${hue(name)} 52% 42%)`, 'aria-hidden': 'true' }, initials(name))
  const when = (ts) => h('time', { datetime: ts, title: ts.replace('T', ' ').replace('Z', ' UTC') }, ago(ts))

  // ---------- validation (same rules as engine/reviews.py) ----------
  function cleanComment(c) {
    if (!c || typeof c !== 'object') return null
    const id = String(c.id || '').toLowerCase()
    if (!ID.test(id) || typeof c.screen !== 'string' || typeof c.body !== 'string' || !c.author) return null
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
      tokens, body: clip(c.body, 4000), author: clip(c.author, 80), created: c.created, modified: c.modified,
    }
  }
  function cleanUpdate(u) {
    if (!u || typeof u !== 'object') return null
    const id = String(u.id || '').toLowerCase()
    if (!ID.test(id) || !UPDATE_STATUSES.includes(u.status) || !TS.test(u.at || '') || !u.by) return null
    const seq = Number.isInteger(u.seq) && u.seq >= 0 ? u.seq : 0
    const out = { id, status: u.status, note: clip(u.note, 1000), by: clip(u.by, 80), via: VIA.includes(u.via) ? u.via : 'file', at: u.at, seq }
    if (typeof u.byId === 'string' && ID.test(u.byId)) out.byId = u.byId
    return out
  }
  // A version-1 file kept the status inside each comment: read it as an update.
  function fromFile(doc) {
    const out = { comments: [], updates: [] }
    if (!doc || doc.format !== 'design-canvas-review' || ![1, 2].includes(doc.schemaVersion)) return null
    for (const raw of Array.isArray(doc.comments) ? doc.comments.slice(0, 500) : []) {
      const c = cleanComment(raw)
      if (!c) continue
      out.comments.push(c)
      if (doc.schemaVersion === 1 && raw.status && raw.status !== 'open') {
        const st = raw.status === 'reopened' ? 'open' : raw.status
        const u = cleanUpdate({ id: c.id, status: st, note: raw.resolution, by: 'earlier review', via: 'file', at: raw.resolvedAt || c.modified, seq: 0 })
        if (u) out.updates.push(u)
      }
    }
    for (const raw of Array.isArray(doc.updates) ? doc.updates.slice(0, 2000) : []) {
      const u = cleanUpdate(raw)
      if (u) out.updates.push(u)
    }
    return out
  }

  // ---------- merge (same rules as engine/reviews.py) ----------
  // Each person's updates in their own `seq` order; people interleaved by time. Only an author can delete.
  function merge(comments, updates) {
    const byId = new Map()
    for (const c of comments) {
      const cur = byId.get(c.id)
      if (!cur || c.modified > cur.modified) byId.set(c.id, { ...c })
    }
    const seen = new Set()
    const writers = new Map()
    for (const u of updates) {
      const k = [u.id, u.status, u.at, u.by, u.seq, u.note].join('\u0001')
      if (seen.has(k)) continue
      seen.add(k)
      if (!writers.has(u.by)) writers.set(u.by, [])
      writers.get(u.by).push(u)
    }
    const queues = [...writers.values()].map((q) => q.sort((a, b) => a.seq - b.seq || byTime(a.at, b.at)))
    const pos = queues.map(() => 0)
    const ordered = []
    for (;;) {
      let best = -1
      for (let i = 0; i < queues.length; i++) {
        if (pos[i] >= queues[i].length) continue
        const u = queues[i][pos[i]]
        const b = best >= 0 ? queues[best][pos[best]] : null
        if (!b || u.at < b.at || (u.at === b.at && u.by < b.by)) best = i
      }
      if (best < 0) break
      ordered.push(queues[best][pos[best]++])
    }
    for (const c of byId.values()) Object.assign(c, { status: 'open', history: [] })
    const deleted = new Set()
    for (const u of ordered) {
      const c = byId.get(u.id)
      if (!c) continue
      if (u.status === 'deleted') {
        if (u.byId ? c.id.startsWith(u.byId + '-') : u.by === c.author) deleted.add(c.id)
        continue
      }
      c.status = u.status
      c.history.push(u)
    }
    return [...byId.values()]
      .filter((c) => !deleted.has(c.id) && !deleted.has(c.replyTo))
      .sort((a, b) => byTime(a.created, b.created) || byTime(a.id, b.id))
  }

  // ---------- who am I, and what I wrote ----------
  const KEY = 'design-canvas.review.' + D.app + (S ? '.' + S.me.slug : '')
  function loadLocal() {
    try {
      const v = JSON.parse(localStorage.getItem(KEY) || '{}')
      return v && typeof v === 'object' ? v : {}
    } catch {
      return {}
    }
  }
  const stored = loadLocal()
  const mine = {
    author: S ? S.me.name : clip(stored.author, 80),
    comments: (Array.isArray(stored.comments) ? stored.comments : []).map(cleanComment).filter(Boolean),
    updates: (Array.isArray(stored.updates) ? stored.updates : []).map(cleanUpdate).filter(Boolean),
    unsent: !!stored.unsent,
  }
  const me = () => (S ? S.me : mine.author ? { name: mine.author, slug: slug(mine.author) } : null)
  function backup() {
    try {
      localStorage.setItem(KEY, JSON.stringify({ author: mine.author, comments: mine.comments, updates: mine.updates, unsent: mine.unsent }))
    } catch {}
  }
  let server = { comments: (D.comments || []).map(cleanComment).filter(Boolean), updates: (D.updates || []).map(cleanUpdate).filter(Boolean) }
  let imported = { comments: [], updates: [] }
  let git = null
  const all = () => merge([...server.comments, ...imported.comments, ...mine.comments], [...server.updates, ...imported.updates, ...mine.updates])
  const topLevel = (list = all()) => list.filter((c) => !c.replyTo)
  const isMine = (c) => !!me() && c.author === me().name && c.id.startsWith(me().slug + '-')

  // ---------- saving ----------
  let stale = false
  let saveState = S ? 'saved' : mine.comments.length || mine.updates.length ? 'local' : 'empty'
  let saveTimer = 0
  const SAVE_TEXT = {
    empty: '',
    local: 'Saved in this browser. Download the review file to send it.',
    unsaved: 'Unsaved changes…',
    saving: 'Saving…',
    saved: 'Saved to your review file.',
    offline: 'Saved in this browser only: the review helper is not running. Restart it to send.',
  }
  async function api(path, body) {
    const r = await fetch('/api/' + path, {
      method: body === undefined ? 'GET' : 'POST',
      headers: { 'X-DC-Token': S.token, 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: 'no-store',
    })
    const j = await r.json().catch(() => ({ ok: false, message: 'The review helper sent an unreadable answer.' }))
    if (!r.ok && j.ok !== false) j.ok = false
    if (r.status === 403) {
      // the helper was restarted (new token) or this page came from somewhere else
      j.message = 'The review helper was restarted. Reload this page to carry on; your comments are kept in this browser.'
      stale = true
    }
    return j
  }
  function persist() {
    mine.unsent = true
    backup()
    if (!S) {
      setSave('local')
      return
    }
    setSave('unsaved')
    clearTimeout(saveTimer)
    saveTimer = setTimeout(flush, 700)
  }
  async function flush() {
    if (!S || !mine.unsent) return true
    clearTimeout(saveTimer)
    setSave('saving')
    try {
      const r = await api('save', { comments: mine.comments, updates: mine.updates })
      if (!r.ok) throw new Error(r.message || 'not saved')
      mine.unsent = false
      backup()
      git = r.git || git
      setSave('saved')
      return true
    } catch (e) {
      setSave('offline')
      notice = { text: stale ? e.message : `Not sent to your review file: ${e.message}. Your comments are kept in this browser.`, error: true }
      alarm(notice.text)
      render()
      return false
    }
  }
  function setSave(st) {
    saveState = st
    const el = drawer.querySelector('.dc-save')
    if (el) el.textContent = SAVE_TEXT[st]
  }

  // ---------- announcements (screen readers) ----------
  const polite = h('div', { class: 'dc-sr', role: 'status', 'aria-live': 'polite', 'aria-atomic': 'true' })
  const urgent = h('div', { class: 'dc-sr', role: 'alert' })
  document.body.append(polite, urgent)
  const announce = (msg) => { polite.textContent = msg }
  const alarm = (msg) => { urgent.textContent = msg }
  let notice = null // { text, error } shown in the panel footer after End review / Get latest

  // ---------- actions ----------
  const nextSeq = () => mine.updates.reduce((m, u) => Math.max(m, u.seq), 0) + 1
  function addComment(el, body) {
    const t = nowIso()
    const info = I.inspect(el)
    const tokens = {}
    for (const r of info.rows) {
      const name = r.tokens[0]?.name || r.guess?.[0]
      if (name && !r.tokens[0]?.unknown) tokens[r.g.key] = name
    }
    mine.comments.push({ id: `${me().slug}-${rand()}`, replyTo: null, screen: el.closest('.cv-frame').dataset.id, built: D.built,
      anchor: I.anchorOf(el), tokens, body, author: me().name, created: t, modified: t })
    persist()
    announce('Comment added.')
    refresh()
  }
  function addReply(parent, body) {
    const t = nowIso()
    mine.comments.push({ id: `${me().slug}-${rand()}`, replyTo: parent.id, screen: parent.screen, built: D.built, anchor: parent.anchor,
      tokens: {}, body, author: me().name, created: t, modified: t })
    persist()
    announce(`Reply added to ${parent.author}'s comment.`)
    refresh()
  }
  function setStatus(c, status, note) {
    mine.updates.push({ id: c.id, status, note: clip(note || '', 1000), by: me().name, byId: me().slug, via: 'browser', at: nowIso(), seq: nextSeq() })
    persist()
    announce(status === 'deleted' ? 'Comment deleted.' : `Comment marked ${STATUS[status].label}.`)
    refresh()
  }
  function remove(c) {
    if (!confirm(`Delete this ${c.replyTo ? 'reply' : 'comment'}? It disappears for everyone once your review is sent.`)) return
    mine.comments = mine.comments.filter((x) => x.id !== c.id && x.replyTo !== c.id)
    setStatus(c, 'deleted', '')
  }
  async function endReview() {
    if (!(await flush())) return
    notice = { text: 'Sending your review…' }
    render()
    let r
    try {
      r = await api('end-review', {})
    } catch {
      r = { ok: false, message: 'The review helper is not running. Start it again, then press End review.' }
    }
    git = r.git || git
    notice = { text: r.message, error: !r.ok }
    ;(r.ok ? announce : alarm)(r.message)
    if (r.ok && r.reload) return location.reload()
    render()
  }
  async function getLatest() {
    if (!(await flush())) return
    notice = { text: 'Getting the latest…' }
    render()
    let r
    try {
      r = await api('get-latest', {})
    } catch {
      r = { ok: false, message: 'The review helper is not running. Start it again, then press Get latest.' }
    }
    git = r.git || git
    notice = { text: r.message, error: !r.ok }
    ;(r.ok ? announce : alarm)(r.message)
    if (r.ok && r.reload) return location.reload()
    await loadState()
  }
  async function loadState() {
    if (!S) return
    try {
      const st = await api('state')
      if (!st.ok) throw new Error(st.message)
      server = { comments: (st.comments || []).map(cleanComment).filter(Boolean), updates: (st.updates || []).map(cleanUpdate).filter(Boolean) }
      git = st.git
      if (!mine.unsent) {
        // the helper's copy of my file is the truth; keep anything newer from this browser
        mine.comments = ((st.mine && st.mine.comments) || []).map(cleanComment).filter(Boolean)
        mine.updates = ((st.mine && st.mine.updates) || []).map(cleanUpdate).filter(Boolean)
        backup()
      } else {
        flush()
      }
    } catch (e) {
      setSave('offline')
      if (stale) notice = { text: e.message, error: true }
    }
    refresh()
  }
  function downloadReview() {
    const who = me()
    const doc = { format: 'design-canvas-review', schemaVersion: 2, app: D.app, exported: nowIso(), author: who ? who.name : 'Reviewer',
      comments: mine.comments.map(cleanComment).filter(Boolean), updates: mine.updates.map(cleanUpdate).filter(Boolean) }
    if (!doc.comments.length && !doc.updates.length) return doc
    const url = URL.createObjectURL(new Blob([JSON.stringify(doc, null, 2) + '\n'], { type: 'application/json' }))
    const a = h('a', { href: url, download: `review-${slug(D.app)}-${doc.exported.slice(0, 10)}-${who ? who.slug : 'reviewer'}.json` })
    document.body.append(a)
    a.click()
    a.remove()
    setTimeout(() => URL.revokeObjectURL(url), 2000)
    announce('Review file downloaded.')
    return doc
  }
  function openFile(f) {
    if (!f) return
    if (f.size > 1_000_000) return alarm('That file is over 1 MB, so it was not opened.')
    const reader = new FileReader()
    reader.onload = () => {
      let doc
      try {
        doc = JSON.parse(String(reader.result))
      } catch {
        return alarm('That file is not valid JSON.')
      }
      const got = fromFile(doc)
      if (!got) return alarm('That is not a design-canvas review file.')
      imported = got
      filter = 'all'
      announce(`Showing ${got.comments.length} comments from the file.`)
      refresh()
    }
    reader.readAsText(f)
  }

  // ---------- hover + selection overlays ----------
  const hover = h('div', { class: 'dc-hover dc-ui', hidden: true }, h('span', { class: 'dc-size' }))
  const selBox = h('div', { class: 'dc-sel dc-ui', hidden: true })
  board.append(hover, selBox)
  let selected = null
  let tab = 'inspect'
  let filter = 'fix'
  let focusId = null
  function place(box, el) {
    if (!el || !el.isConnected || el.closest('.cv-page')?.hidden) {
      box.hidden = true
      return
    }
    const b = board.getBoundingClientRect(), r = el.getBoundingClientRect()
    Object.assign(box.style, { left: `${r.left - b.left}px`, top: `${r.top - b.top}px`, width: `${r.width}px`, height: `${r.height}px` })
    box.hidden = false
  }
  let raf = 0
  board.addEventListener('pointermove', (e) => {
    if (!C.inspecting() || e.buttons) {
      hover.hidden = true
      return
    }
    cancelAnimationFrame(raf)
    raf = requestAnimationFrame(() => {
      const el = I.pickable(document.elementFromPoint(e.clientX, e.clientY), e.clientX, e.clientY)
      if (!el) {
        hover.hidden = true
        return
      }
      place(hover, el)
      const dev = el.closest('.dev')
      const k = dev.getBoundingClientRect().width / dev.offsetWidth || 1
      const r = el.getBoundingClientRect()
      hover.firstChild.textContent = `${Math.round(r.width / k)} × ${Math.round(r.height / k)}`
    })
  })
  board.addEventListener('pointerleave', () => { hover.hidden = true })

  // ---------- the panel ----------
  function setInspect(on) {
    document.body.classList.toggle('dc-inspecting', on)
    btnInspect.setAttribute('aria-pressed', String(on))
    hover.hidden = true
    if (on) openDrawer('inspect')
    announce(on ? 'Inspect on: click any element on a screen.' : 'Inspect off.')
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
  function nameField() {
    return h('input', { class: 'dc-name', type: 'text', maxlength: '80', placeholder: 'Your name', value: mine.author || '', 'aria-label': 'Your name' })
  }
  function composer(onSave, label, placeholder, optional) {
    const name = me() ? null : nameField()
    const box = h('textarea', { class: 'dc-text', rows: '3', maxlength: '4000', placeholder, 'aria-label': label })
    const err = h('p', { class: 'dc-err', role: 'alert' })
    const go = h('button', {
      type: 'button', class: 'dc-btn primary',
      onclick: () => {
        err.textContent = ''
        if (name) {
          const n = clip(name.value.trim(), 80)
          if (!n) return (err.textContent = 'Add your name first.'), name.focus()
          mine.author = n
          backup()
        }
        const body = clip(box.value.trim(), 4000)
        if (!body && !optional) return (err.textContent = 'Write something first.'), box.focus()
        onSave(body)
      },
    }, label)
    return h('div', { class: 'dc-compose' }, name, box, err, go,
      !S && mine.author ? h('button', { type: 'button', class: 'dc-link', onclick: () => { mine.author = ''; backup(); render() } }, `Commenting as ${mine.author} · change`) : null)
  }
  function statusChip(c) {
    const s = STATUS[c.status]
    return h('span', { class: `dc-status g-${s.group}` }, s.label)
  }
  function lastLine(c) {
    const u = c.history[c.history.length - 1]
    if (!u) return null
    const via = u.via === 'cli' || u.via === 'mcp' ? ' via agent' : ''
    return h('p', { class: 'dc-update' }, h('b', {}, STATUS[u.status].label), ` · ${u.by}${via} · `, when(u.at), u.note ? `: ${u.note}` : '')
  }
  function inline(parent, label, placeholder, optional, onSave) {
    const box = h('div', { class: 'dc-reply' }, composer(onSave, label, placeholder, optional))
    parent.after(box)
    box.querySelector('textarea').focus()
  }
  function actions(c) {
    const row = h('div', { class: 'dc-actions' })
    const add = (label, fn) => row.append(h('button', { type: 'button', class: 'dc-link', onclick: fn }, label))
    const needName = () => { if (!me()) { openDrawer('comments'); alarm('Add your name first: write a comment or reply.'); return true } return false }
    add('Show', () => show(c))
    if (!c.replyTo) {
      const g = STATUS[c.status].group
      if (g === 'fix' || c.status === 'question') {
        add('Reply', () => !needName() && inline(row, 'Reply', 'Reply…', false, (b) => addReply(c, b)))
        add('Mark fix ready', () => !needName() && inline(row, 'Mark fix ready', 'What changed? (optional)', true, (b) => setStatus(c, 'ready', b)))
      }
      if (g === 'fix') {
        add('Ask a question', () => !needName() && inline(row, 'Ask', 'What do you need to know?', false, (b) => setStatus(c, 'question', b)))
        add("Won't fix", () => !needName() && inline(row, "Won't fix", 'Why not? (optional)', true, (b) => setStatus(c, 'wontfix', b)))
      }
      if (c.status === 'ready') {
        add('Resolve', () => !needName() && setStatus(c, 'resolved', ''))
        add('Reopen', () => !needName() && inline(row, 'Reopen', "What's still not right? (optional)", true, (b) => setStatus(c, 'open', b || 'Reopened')))
      }
      if (g === 'closed') add('Reopen', () => !needName() && inline(row, 'Reopen', "What's still not right? (optional)", true, (b) => setStatus(c, 'open', b || 'Reopened')))
    }
    if (isMine(c)) add('Delete', () => remove(c))
    return row
  }
  function card(c, list, number, compact) {
    const replies = list.filter((x) => x.replyTo === c.id)
    const scr = D.screens[c.screen]
    const s = STATUS[c.status]
    return h('article', { class: `dc-card${focusId === c.id ? ' focus' : ''}`, 'data-id': c.id },
      h('header', {},
        number ? h('span', { class: `dc-num g-${s.group}`, 'aria-hidden': 'true' }, String(number) + s.mark) : null,
        avatar(c.author), h('b', { class: 'dc-who' }, c.author), h('span', { class: 'dc-muted' }, ' · ', when(c.created)),
        c.replyTo ? null : statusChip(c)),
      compact || c.replyTo ? null : h('div', { class: 'dc-muted dc-where' }, scr ? scr.title : `${c.screen} (screen not on the canvas)`, c.anchor?.text ? ` · “${c.anchor.text.slice(0, 50)}”` : ''),
      h('p', { class: 'dc-body' }, c.body),
      c.replyTo ? null : lastLine(c),
      actions(c),
      replies.length ? h('div', { class: 'dc-replies' }, replies.map((r) => card(r, list, 0, true))) : null)
  }
  function inspectView() {
    if (!selected || !selected.isConnected) {
      return h('div', { class: 'dc-empty' },
        h('p', {}, C.inspecting() ? 'Click anything on a screen to see its size and the design tokens it uses.' : 'Turn on Inspect and click anything on a screen to see its size and the design tokens it uses.'),
        h('p', { class: 'dc-muted' }, 'Keys: I inspect, C comments, Esc close.'))
    }
    const info = I.inspect(selected)
    const fig = selected.closest('.cv-frame')
    const scr = D.screens[fig.dataset.id] || {}
    const list = all()
    const here = topLevel(list).filter((c) => c.screen === fig.dataset.id && I.findAnchor(c)?.el === selected)
    return h('div', { class: 'dc-inspect' },
      h('div', { class: 'dc-head' },
        h('code', { class: 'dc-el' }, I.describeEl(selected)),
        h('div', { class: 'dc-muted' }, `${scr.title || fig.dataset.id} · ${scr.state || ''}`),
        scr.source ? h('code', { class: 'dc-src' }, scr.source) : null,
        info.component ? h('div', {}, 'Component ', h('span', { class: 'dc-tok' }, info.component)) : null),
      h('dl', { class: 'dc-rows' },
        h('dt', {}, 'Size'), h('dd', {}, `${info.w} × ${info.h}`),
        info.rows.map((r) => [
          h('dt', {}, r.g.label),
          h('dd', {},
            r.tokens.length ? h('div', { class: 'dc-toks' }, r.tokens.map(chip)) : null,
            !r.tokens.length && r.guess?.length ? h('div', { class: 'dc-toks' }, r.guess.map((n) => h('span', { class: 'dc-tok guess', title: 'matched by value' }, n)), h('small', { class: 'dc-muted' }, ' by value')) : null,
            r.raw.length ? h('div', { class: 'dc-off' }, 'Off-system: ', r.raw.join(', ')) : null,
            r.notes.length ? h('div', { class: 'dc-muted' }, 'Overridden: ', r.notes.join('; ')) : null,
            r.value ? h('div', { class: 'dc-val' }, r.value) : null,
            r.from ? h('div', { class: 'dc-muted' }, 'inherited from ', h('code', {}, I.describeEl(r.from))) : null),
        ]),
        info.text ? [h('dt', {}, 'Text'), h('dd', { class: 'dc-quote' }, info.text.slice(0, 120))] : null),
      info.flags.length ? h('p', { class: 'dc-off-note' }, `${info.flags.length} value${info.flags.length > 1 ? 's are' : ' is'} typed by hand instead of using a token.`) : null,
      here.length ? h('div', { class: 'dc-here' }, h('h4', {}, 'Comments here'), here.map((c) => card(c, list, 0, true))) : null,
      composer((b) => addComment(selected, b), 'Add comment', 'What should change? Be specific: "make this 16 not 14", "use the accent colour"…'))
  }
  function counts(list) {
    const top = topLevel(list)
    return {
      fix: top.filter((c) => STATUS[c.status].group === 'fix').length,
      check: top.filter((c) => STATUS[c.status].group === 'check').length,
      all: top.length,
    }
  }
  function commentsView() {
    const list = all()
    const n = counts(list)
    const top = topLevel(list)
    const shown = top.filter((c) => filter === 'all' || STATUS[c.status].group === filter)
    const pick = (key, label) => h('button', { type: 'button', 'aria-pressed': String(filter === key), onclick: () => { filter = key; render() } }, `${label} (${n[key]})`)
    return h('div', { class: 'dc-comments' },
      h('div', { class: 'dc-filter', role: 'group', 'aria-label': 'Show comments' }, pick('fix', 'Needs fix'), pick('check', 'To check'), pick('all', 'All')),
      shown.length ? shown.map((c) => card(c, list, top.indexOf(c) + 1, false))
        : h('p', { class: 'dc-empty' }, filter === 'fix' ? 'Nothing needs a fix.' : filter === 'check' ? 'Nothing to check.' : 'No comments yet. Turn on Inspect, click an element and add one.'),
      imported.comments.length ? h('p', { class: 'dc-muted' }, `Including ${imported.comments.length} comment(s) from an opened file (not saved).`) : null)
  }
  function footer() {
    const who = me()
    const file = h('input', { type: 'file', accept: 'application/json,.json', hidden: true, onchange: (e) => openFile(e.target.files[0]) })
    const parts = []
    if (S) {
      const g = git || {}
      parts.push(h('p', { class: 'dc-gitline' }, avatar(S.me.name), h('b', {}, S.me.name),
        g.repo ? ` · on ${g.branch || 'no branch'}${g.ahead ? ` · ${g.ahead} to push` : ''}${g.behind ? ` · ${g.behind} new on the remote` : ''}` : ' · not a git repository'))
      const canGit = g.repo && !g.detached
      parts.push(h('div', { class: 'dc-buttons' },
        h('button', { type: 'button', class: 'dc-btn primary', disabled: !canGit, onclick: endReview }, 'End review'),
        h('button', { type: 'button', class: 'dc-btn', disabled: !canGit || !g.upstream, onclick: getLatest }, 'Get latest'),
        h('button', { type: 'button', class: 'dc-link', onclick: downloadReview }, 'Download review file')))
      if (g.repo === false) parts.push(h('p', { class: 'dc-muted' }, g.why || ''))
    } else {
      parts.push(h('p', { class: 'dc-gitline' }, who ? [avatar(who.name), h('b', {}, who.name)] : 'Not signed: add your name with your first comment.'))
      parts.push(h('div', { class: 'dc-buttons' },
        h('button', { type: 'button', class: 'dc-btn primary', disabled: !(mine.comments.length || mine.updates.length), onclick: downloadReview }, 'Download review file'),
        h('button', { type: 'button', class: 'dc-btn', onclick: () => file.click() }, 'Open review file'), file))
    }
    parts.push(h('p', { class: 'dc-save dc-muted', 'aria-live': 'off' }, SAVE_TEXT[saveState]))
    if (notice) parts.push(h('p', { class: `dc-notice${notice.error ? ' error' : ''}` }, notice.text))
    return h('footer', { class: 'dc-foot' }, parts)
  }
  function render() {
    if (drawer.hidden) return
    const n = counts(all())
    const tabBtn = (key, label) => h('button', { type: 'button', 'aria-pressed': String(tab === key), onclick: () => { tab = key; render() } }, label)
    const focusTarget = document.activeElement && drawer.contains(document.activeElement) ? document.activeElement.textContent : null
    drawer.replaceChildren(
      h('div', { class: 'dc-tabs' }, tabBtn('inspect', 'Inspect'), tabBtn('comments', `Comments (${n.fix} to fix · ${n.check} to check)`),
        h('button', { type: 'button', class: 'dc-close', 'aria-label': 'Close panel', onclick: closeDrawer }, '×')),
      h('div', { class: 'dc-scroll' }, tab === 'inspect' ? inspectView() : commentsView()),
      footer())
    if (focusTarget) [...drawer.querySelectorAll('button')].find((b) => b.textContent === focusTarget)?.focus()
    if (focusId) drawer.querySelector(`.dc-card[data-id="${CSS.escape(focusId)}"]`)?.scrollIntoView({ block: 'nearest' })
  }
  function refresh() {
    const n = counts(all())
    countEl.textContent = n.check ? `${n.fix} · ${n.check}✓` : String(n.fix)
    btnComments.setAttribute('aria-label', `Comments: ${n.fix} need a fix, ${n.check} to check`)
    drawPins()
    render()
  }
  function show(c) {
    const scr = D.screens[c.screen]
    if (scr && scr.page !== C.current) C.showPage(scr.page, true)
    requestAnimationFrame(() => {
      const f = I.findAnchor(c)
      if (!f) return
      C.zoomToFrame(f.fig)
      focusId = c.id
      if (f.el) {
        selected = f.el
        requestAnimationFrame(() => place(selBox, f.el))
      }
      render()
    })
  }

  // ---------- pins ----------
  function drawPins() {
    world.querySelectorAll('.dc-pin').forEach((p) => p.remove())
    topLevel().forEach((c, i) => {
      const f = I.findAnchor(c)
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
      const s = STATUS[c.status]
      const pin = h('button', {
        type: 'button', class: `dc-pin g-${s.group}${f.el ? '' : ' is-detached'}`, 'data-id': c.id,
        'aria-label': `Comment ${i + 1}, ${s.label}, by ${c.author}`,
        title: `${i + 1} · ${s.label} · ${c.author}: ${c.body.slice(0, 80)}${f.el ? '' : ' (element moved; shown at its old place)'}`,
      }, String(i + 1) + s.mark)
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
  addEventListener('dc:pick', (e) => select(I.pickable(e.detail.target, e.detail.x, e.detail.y)))
  addEventListener('dc:pin', (e) => {
    const c = all().find((x) => x.id === e.detail.id)
    if (!c) return
    focusId = c.id
    filter = 'all'
    openDrawer('comments')
    const f = I.findAnchor(c)
    if (f?.el) {
      selected = f.el
      place(selBox, f.el)
    }
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
    const v = loadLocal()
    mine.comments = (Array.isArray(v.comments) ? v.comments : []).map(cleanComment).filter(Boolean)
    mine.updates = (Array.isArray(v.updates) ? v.updates : []).map(cleanUpdate).filter(Boolean)
    refresh()
  })
  addEventListener('beforeunload', (e) => {
    if (S && mine.unsent) {
      e.preventDefault()
      e.returnValue = ''
    }
  })
  window.DC_REVIEW = { all, merge, mine, reviewDoc: () => ({ comments: mine.comments, updates: mine.updates }), select, flush, loadState, setStatus }
  refresh()
  if (S) loadState()
  document.fonts?.ready.then(drawPins)
})()
