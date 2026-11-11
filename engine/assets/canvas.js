;(() => {
  const data = window.CANVAS
  const board = document.getElementById('board')
  const world = document.getElementById('world')
  const pct = document.getElementById('zpct')
  const framesEl = document.getElementById('frames')
  const find = document.getElementById('find')
  const app = document.getElementById('app')
  const calm = matchMedia('(prefers-reduced-motion: reduce)').matches
  let view = { x: 0, y: 0, k: 0.2 }
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c])
  let current = null

  const store = {
    get(k) {
      try {
        return localStorage.getItem(k)
      } catch {
        return null
      }
    },
    set(k, v) {
      try {
        localStorage.setItem(k, v)
      } catch {}
    },
  }

  // ---------- view transform ----------
  function apply(animate) {
    world.style.transition =
      animate && !calm ? 'transform 260ms cubic-bezier(0.2, 0.8, 0.2, 1)' : 'none'
    world.style.transform = `translate(${view.x}px, ${view.y}px) scale(${view.k})`
    pct.textContent = `${Math.round(view.k * 100)}%`
    window.dispatchEvent(new CustomEvent('dc:view'))
  }
  const clamp = (k) => Math.min(3, Math.max(0.04, k))
  function zoomAt(px, py, k, animate) {
    k = clamp(k)
    view.x = px - (px - view.x) * (k / view.k)
    view.y = py - (py - view.y) * (k / view.k)
    view.k = k
    apply(animate)
  }
  function pageEl() {
    return world.querySelector(`.cv-page[data-page="${current}"]`)
  }
  function fit(animate = true) {
    const el = pageEl()
    if (!el) return
    const bw = board.clientWidth,
      bh = board.clientHeight
    const w = el.offsetWidth,
      h = el.offsetHeight
    // fit the width of the page, but never so small the first row is unreadable
    const k = clamp(Math.min(bw / w, Math.max(bh / h, (bw / w) * 0.9)) * 0.96)
    view.k = k
    view.x = (bw - w * k) / 2
    view.y = Math.max(16, (bh - h * k) / 2)
    if (h * k > bh) view.y = 16
    apply(animate)
  }
  function zoomToFrame(fig, animate = true) {
    const phone = fig.querySelector('.dev')
    const r = rectInWorld(fig)
    const ph = rectInWorld(phone)
    const bw = board.clientWidth,
      bh = board.clientHeight
    const k = clamp(
      Math.min(1.1, (bh - 48) / Math.min(ph.h + (ph.y - r.y), 1100), (bw - 48) / (r.w + 80)),
    )
    view.k = k
    view.x = bw / 2 - (r.x + r.w / 2) * k
    view.y = 24 - r.y * k
    apply(animate)
    world.querySelectorAll('.cv-frame.sel').forEach((f) => f.classList.remove('sel'))
    fig.classList.add('sel')
    framesEl
      .querySelectorAll('button')
      .forEach((b) => b.classList.toggle('on', b.dataset.id === fig.dataset.id))
  }
  function rectInWorld(el) {
    const wr = world.getBoundingClientRect()
    const r = el.getBoundingClientRect()
    return {
      x: (r.left - wr.left) / view.k,
      y: (r.top - wr.top) / view.k,
      w: r.width / view.k,
      h: r.height / view.k,
    }
  }

  // ---------- flow arrows ----------
  function drawLinks() {
    const el = pageEl()
    if (!el) return
    el.querySelector('.cv-links')?.remove()
    const svgNS = 'http://www.w3.org/2000/svg'
    const svg = document.createElementNS(svgNS, 'svg')
    svg.classList.add('cv-links')
    svg.setAttribute('width', el.offsetWidth)
    svg.setAttribute('height', el.offsetHeight)
    const base = rectInWorld(el)
    const phoneRect = (id) => {
      const f = el.querySelector(`.cv-frame[data-id="${id}"] .dev`)
      if (!f) return null
      const r = rectInWorld(f)
      return { x: r.x - base.x, y: r.y - base.y, w: r.w, h: r.h }
    }
    const path = (d, dashed) => {
      const p = document.createElementNS(svgNS, 'path')
      p.setAttribute('d', d)
      if (dashed) p.classList.add('x')
      svg.appendChild(p)
    }
    const label = (x, y, text) => {
      const t = document.createElementNS(svgNS, 'text')
      t.setAttribute('x', x)
      t.setAttribute('y', y)
      t.setAttribute('text-anchor', 'middle')
      t.textContent = text
      svg.appendChild(t)
    }
    // consecutive frames in a flow row
    el.querySelectorAll('.cv-row[data-flow] .cv-row-frames').forEach((row) => {
      const ids = [...row.querySelectorAll(':scope > .cv-frame')].map((f) => f.dataset.id)
      for (let i = 0; i + 1 < ids.length; i++) {
        const a = phoneRect(ids[i]),
          b = phoneRect(ids[i + 1])
        if (!a || !b) continue
        const y = a.y + Math.min(210, a.h * 0.25)
        const x1 = a.x + a.w + 14,
          x2 = b.x - 14
        path(`M${x1} ${y} H${x2 - 12} M${x2 - 22} ${y - 10} L${x2} ${y} L${x2 - 22} ${y + 10}`)
      }
    })
    // explicit links (branches, jumps between rows)
    for (const [from, to, text] of data.pages.find((p) => p.id === current)?.links || []) {
      const a = phoneRect(from),
        b = phoneRect(to)
      if (!a || !b) continue
      let x1, y1, x2, y2, d
      if (Math.abs(a.y - b.y) < 40) {
        // same row: arc over the top of the row instead of through the frames between
        x1 = a.x + a.w / 2
        x2 = b.x + b.w / 2
        y1 = y2 = a.y - 150
        const lift = Math.min(260, 80 + Math.abs(x2 - x1) * 0.08)
        path(`M${x1} ${y1} C${x1} ${y1 - lift} ${x2} ${y2 - lift} ${x2} ${y2}`, true)
        path(`M${x2 - 10} ${y2 - 20} L${x2} ${y2} L${x2 + 10} ${y2 - 20}`)
        if (text) label((x1 + x2) / 2, y1 - lift * 0.75 - 12, text)
        continue
      }
      if (b.y > a.y + a.h) {
        x1 = a.x + a.w / 2
        y1 = a.y + a.h + 14
        x2 = b.x + b.w / 2
        y2 = b.y - 70
        const my = (y1 + y2) / 2
        d = `M${x1} ${y1} C${x1} ${my} ${x2} ${my} ${x2} ${y2}`
        path(d, true)
        path(`M${x2 - 10} ${y2 - 20} L${x2} ${y2} L${x2 + 10} ${y2 - 20}`)
        if (text) label((x1 + x2) / 2, my - 12, text)
      } else {
        x1 = a.x + a.w + 14
        y1 = a.y + a.h * 0.5
        x2 = b.x - 14
        y2 = b.y + b.h * 0.5
        const mx = (x1 + x2) / 2
        path(`M${x1} ${y1} C${mx} ${y1} ${mx} ${y2} ${x2} ${y2}`, true)
        path(`M${x2 - 22} ${y2 - 10} L${x2} ${y2} L${x2 - 22} ${y2 + 10}`)
        if (text) label(mx, Math.min(y1, y2) - 16, text)
      }
    }
    el.prepend(svg)
  }

  // ---------- pages ----------
  function showPage(id, keepView) {
    if (!data.pages.some((p) => p.id === id)) id = data.pages[0].id
    current = id
    world.querySelectorAll('.cv-page').forEach((p) => (p.hidden = p.dataset.page !== id))
    document
      .querySelectorAll('[data-goto]')
      .forEach((b) => b.classList.toggle('on', b.dataset.goto === id))
    const page = data.pages.find((p) => p.id === id)
    framesEl.innerHTML = page.rows
      .map(
        (row) =>
          `<div class="grp">${esc(row.title)}</div>` +
          row.frames
            .map(
              (f) =>
                `<button type="button" data-id="${esc(f.id)}"><b>${esc(f.title)}</b><span>${esc(f.state)}</span></button>`,
            )
            .join(''),
      )
      .join('')
    find.value = ''
    store.set('design-canvas.page', id)
    if (location.hash.slice(1) !== id) history.replaceState(null, '', `#${id}`)
    requestAnimationFrame(() => {
      drawLinks()
      if (!keepView) fit(false)
      window.dispatchEvent(new CustomEvent('dc:page', { detail: { id } }))
    })
    document
      .querySelector(`.chips [data-goto="${id}"]`)
      ?.scrollIntoView({ inline: 'center', block: 'nearest' })
  }
  document.addEventListener('click', (e) => {
    const go = e.target.closest('[data-goto]')
    if (go) {
      showPage(go.dataset.goto)
      app.classList.remove('show-side')
    }
    const fb = e.target.closest('#frames button')
    if (fb) {
      const fig = world.querySelector(`.cv-frame[data-id="${fb.dataset.id}"]`)
      if (fig) zoomToFrame(fig)
      app.classList.remove('show-side')
    }
  })
  find.addEventListener('input', () => {
    const q = find.value.trim().toLowerCase()
    framesEl
      .querySelectorAll('button')
      .forEach((b) => (b.hidden = q && !b.textContent.toLowerCase().includes(q)))
  })
  document.getElementById('menu').addEventListener('click', () => app.classList.add('show-side'))
  document
    .getElementById('side-close')
    .addEventListener('click', () => app.classList.remove('show-side'))

  // ---------- pointer: drag to pan, pinch to zoom, click a label to focus ----------
  const pointers = new Map()
  let drag = null,
    pinch = null
  const inspecting = () => document.body.classList.contains('dc-inspecting')
  board.addEventListener('pointerdown', (e) => {
    if (e.target.closest('.zoom, .dc-ui')) return
    board.setPointerCapture(e.pointerId)
    pointers.set(e.pointerId, { x: e.clientX, y: e.clientY })
    if (pointers.size === 1)
      drag = { x: e.clientX, y: e.clientY, vx: view.x, vy: view.y, moved: false, target: e.target }
    if (pointers.size === 2) {
      const [a, b] = [...pointers.values()]
      pinch = { d: Math.hypot(a.x - b.x, a.y - b.y), k: view.k }
      drag = null
    }
  })
  board.addEventListener('pointermove', (e) => {
    if (!pointers.has(e.pointerId)) return
    pointers.set(e.pointerId, { x: e.clientX, y: e.clientY })
    if (pinch && pointers.size === 2) {
      const [a, b] = [...pointers.values()]
      const r = board.getBoundingClientRect()
      zoomAt(
        (a.x + b.x) / 2 - r.left,
        (a.y + b.y) / 2 - r.top,
        pinch.k * (Math.hypot(a.x - b.x, a.y - b.y) / pinch.d),
      )
      return
    }
    if (!drag) return
    const dx = e.clientX - drag.x,
      dy = e.clientY - drag.y
    if (!drag.moved && Math.hypot(dx, dy) < 4) return
    drag.moved = true
    board.classList.add('grabbing')
    view.x = drag.vx + dx
    view.y = drag.vy + dy
    apply(false)
  })
  const end = (e) => {
    pointers.delete(e.pointerId)
    if (pointers.size < 2) pinch = null
    if (drag && !drag.moved && e.type === 'pointerup') {
      if (drag.target.closest?.('.dc-pin')) {
        window.dispatchEvent(new CustomEvent('dc:pin', { detail: { id: drag.target.closest('.dc-pin').dataset.id } }))
      } else if (inspecting()) {
        window.dispatchEvent(new CustomEvent('dc:pick', { detail: { target: drag.target } }))
      } else {
        const fig = drag.target.closest?.('.cv-frame')
        if (fig) zoomToFrame(fig)
      }
    }
    if (pointers.size === 0) {
      drag = null
      board.classList.remove('grabbing')
    }
  }
  board.addEventListener('pointerup', end)
  board.addEventListener('pointercancel', end)
  board.addEventListener(
    'wheel',
    (e) => {
      if (e.target.closest('.dc-ui')) return
      e.preventDefault()
      const r = board.getBoundingClientRect()
      if (e.ctrlKey || e.metaKey) {
        zoomAt(e.clientX - r.left, e.clientY - r.top, view.k * Math.exp(-e.deltaY * 0.01))
      } else {
        view.x -= e.deltaX
        view.y -= e.deltaY
        apply(false)
      }
    },
    { passive: false },
  )

  // ---------- controls ----------
  const center = () => [board.clientWidth / 2, board.clientHeight / 2]
  document
    .getElementById('zin')
    .addEventListener('click', () => zoomAt(...center(), view.k * 1.4, true))
  document
    .getElementById('zout')
    .addEventListener('click', () => zoomAt(...center(), view.k / 1.4, true))
  document.getElementById('zfit').addEventListener('click', () => fit(true))
  pct.addEventListener('click', () => zoomAt(...center(), 1, true))
  document.addEventListener('keydown', (e) => {
    if (e.target.closest('input, textarea, select, [contenteditable]') || e.metaKey || e.ctrlKey || e.altKey) return
    const ids = data.pages.map((p) => p.id)
    const i = ids.indexOf(current)
    if (e.key === '0') fit(true)
    else if (e.key === '1') zoomAt(...center(), 1, true)
    else if (e.key === '+' || e.key === '=') zoomAt(...center(), view.k * 1.4, true)
    else if (e.key === '-') zoomAt(...center(), view.k / 1.4, true)
    else if (e.key === ']') showPage(ids[(i + 1) % ids.length])
    else if (e.key === '[') showPage(ids[(i - 1 + ids.length) % ids.length])
    else if (e.key === 'Escape') app.classList.remove('show-side')
  })
  let resizeTimer
  addEventListener('resize', () => {
    clearTimeout(resizeTimer)
    resizeTimer = setTimeout(() => fit(false), 150)
  })
  addEventListener('hashchange', () => showPage(location.hash.slice(1)))

  window.DC_CANVAS = {
    board, world,
    get view() { return view },
    get current() { return current },
    showPage, zoomToFrame, inspecting,
  }
  showPage(location.hash.slice(1) || store.get('design-canvas.page') || data.pages[0].id)
  document.fonts?.ready.then(() => {
    drawLinks()
    fit(false)
  })
})()
