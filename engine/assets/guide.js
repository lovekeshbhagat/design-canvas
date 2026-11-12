;(() => {
  const store = {
    get(k) { try { return localStorage.getItem(k) } catch { return null } },
    set(k, v) { try { localStorage.setItem(k, v) } catch {} },
  }

  // Theme switch: swaps the app tokens and matches the guide chrome to the theme.
  const schemes = window.DG_SCHEMES || {}
  const root = document.documentElement
  const buttons = [...document.querySelectorAll('[data-set-theme]')]
  const menu = document.querySelector('[data-theme-select]') // many themes: a menu instead of buttons
  function setTheme(id) {
    if (!(id in schemes)) return
    root.dataset.theme = id
    root.dataset.scheme = schemes[id]
    buttons.forEach((b) => b.classList.toggle('on', b.dataset.setTheme === id))
    if (menu) menu.value = id
    store.set('design-canvas.theme', id)
  }
  buttons.forEach((b) => b.addEventListener('click', () => setTheme(b.dataset.setTheme)))
  menu?.addEventListener('change', () => setTheme(menu.value))
  setTheme(store.get('design-canvas.theme') || root.dataset.theme)

  // Highlight the chapter in view.
  const links = [...document.querySelectorAll('.nav-group a[href^="#"]')]
  const byId = new Map(links.map((a) => [a.getAttribute('href').slice(1), a]))
  const io = new IntersectionObserver(
    (entries) => {
      for (const e of entries) {
        if (!e.isIntersecting) continue
        links.forEach((a) => a.classList.remove('on'))
        const a = byId.get(e.target.id)
        if (!a) continue
        a.classList.add('on')
        if (getComputedStyle(a.parentElement).flexDirection === 'row') a.scrollIntoView({ block: 'nearest', inline: 'center' })
      }
    },
    { rootMargin: '-30% 0px -60% 0px' },
  )
  document.querySelectorAll('section.chapter').forEach((s) => io.observe(s))

  // Find a part: filters the part cards by name and text.
  const input = document.getElementById('find')
  const parts = [...document.querySelectorAll('article.part')]
  input?.addEventListener('input', () => {
    const q = input.value.trim().toLowerCase()
    let first = null
    for (const p of parts) {
      const hit = !q || p.textContent.toLowerCase().includes(q)
      p.hidden = !hit
      if (hit && q && !first) first = p
    }
    if (first && first.querySelector('h3').textContent.toLowerCase().includes(q)) first.scrollIntoView({ block: 'start' })
  })
})()
