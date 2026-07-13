(() => {
  const key = 'weinsight.sidebar.v1';
  const shell = document.querySelector('.app-shell');
  const sidebar = document.getElementById('app-sidebar');
  const desktopToggle = document.getElementById('sidebar-toggle');
  const mobileToggle = document.getElementById('mobile-nav-toggle');
  const backdrop = document.getElementById('nav-backdrop');
  if (!shell || !sidebar) return;

  const setCollapsed = (collapsed) => {
    shell.dataset.sidebarState = collapsed ? 'collapsed' : 'expanded';
    desktopToggle?.setAttribute('aria-expanded', String(!collapsed));
    localStorage.setItem(key, collapsed ? 'collapsed' : 'expanded');
  };
  const closeDrawer = () => {
    shell.classList.remove('nav-open');
    mobileToggle?.setAttribute('aria-expanded', 'false');
    if (backdrop) backdrop.hidden = true;
  };
  setCollapsed(localStorage.getItem(key) === 'collapsed');
  desktopToggle?.addEventListener('click', () => setCollapsed(shell.dataset.sidebarState !== 'collapsed'));
  mobileToggle?.addEventListener('click', () => {
    shell.classList.add('nav-open');
    mobileToggle.setAttribute('aria-expanded', 'true');
    if (backdrop) backdrop.hidden = false;
  });
  backdrop?.addEventListener('click', closeDrawer);
  document.addEventListener('keydown', (event) => { if (event.key === 'Escape') closeDrawer(); });
  sidebar.querySelectorAll('a').forEach((link) => link.addEventListener('click', closeDrawer));
})();
