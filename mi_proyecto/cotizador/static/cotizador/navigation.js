(() => {
  const shell = document.querySelector('.shell');
  const toggle = document.querySelector('.rail-toggle');
  if (!shell || !toggle) return;

  const storageKey = 'cintac-navigation-collapsed';
  const setCollapsed = (collapsed) => {
    shell.classList.toggle('nav-collapsed', collapsed);
    toggle.setAttribute('aria-expanded', String(!collapsed));
    toggle.setAttribute('aria-label', collapsed ? 'Mostrar menú' : 'Ocultar menú');
    toggle.title = collapsed ? 'Mostrar menú' : 'Ocultar menú';
  };

  setCollapsed(localStorage.getItem(storageKey) === 'true');
  toggle.addEventListener('click', () => {
    const collapsed = !shell.classList.contains('nav-collapsed');
    setCollapsed(collapsed);
    localStorage.setItem(storageKey, String(collapsed));
  });
})();
