(() => {
  const storageKey = 'cintac-color-theme';
  const root = document.documentElement;
  const readTheme = () => {
    try {
      return localStorage.getItem(storageKey) === 'dark' ? 'dark' : 'light';
    } catch (error) {
      return 'light';
    }
  };
  const setTheme = (theme) => {
    root.dataset.theme = theme;
    const toggle = document.querySelector('.theme-toggle');
    if (!toggle) return;
    const isDark = theme === 'dark';
    toggle.setAttribute('aria-pressed', String(isDark));
    toggle.setAttribute('aria-label', isDark ? 'Activar modo claro' : 'Activar modo oscuro');
    toggle.title = isDark ? 'Activar modo claro' : 'Activar modo oscuro';
  };

  setTheme(readTheme());
  document.addEventListener('DOMContentLoaded', () => {
    const toggle = document.querySelector('.theme-toggle');
    if (!toggle) return;
    setTheme(root.dataset.theme);
    toggle.addEventListener('click', () => {
      const theme = root.dataset.theme === 'dark' ? 'light' : 'dark';
      setTheme(theme);
      try {
        localStorage.setItem(storageKey, theme);
      } catch (error) {
        // El cambio permanece activo en la página aunque el almacenamiento esté bloqueado.
      }
    });
  });
})();
