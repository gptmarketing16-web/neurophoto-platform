(() => {
  const root = document.documentElement;
  const stored = localStorage.getItem('neurophoto-theme');
  const preferredDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
  const initial = stored || (preferredDark ? 'dark' : 'light');
  root.dataset.theme = initial;

  function updateButtons() {
    document.querySelectorAll('[data-theme-toggle]').forEach((button) => {
      const dark = root.dataset.theme === 'dark';
      button.setAttribute('aria-label', dark ? 'Включить светлую тему' : 'Включить тёмную тему');
      button.setAttribute('title', dark ? 'Светлая тема' : 'Тёмная тема');
      button.querySelector('[data-theme-icon]').textContent = dark ? '☀' : '◐';
    });
  }

  document.addEventListener('click', (event) => {
    const button = event.target.closest('[data-theme-toggle]');
    if (!button) return;
    root.dataset.theme = root.dataset.theme === 'dark' ? 'light' : 'dark';
    localStorage.setItem('neurophoto-theme', root.dataset.theme);
    updateButtons();
  });

  window.addEventListener('DOMContentLoaded', updateButtons);
})();
