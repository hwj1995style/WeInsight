(() => {
  const key = 'weinsight.sidebar.v1';
  const shell = document.querySelector('.app-shell');
  const sidebar = document.getElementById('app-sidebar');
  const desktopToggle = document.getElementById('sidebar-toggle');
  const mobileToggle = document.getElementById('mobile-nav-toggle');
  const backdrop = document.getElementById('nav-backdrop');
  const appMain = document.getElementById('app-main');
  if (!shell || !sidebar) return;

  const readSidebarState = () => {
    try {
      return localStorage.getItem(key);
    } catch {
      return null;
    }
  };
  const persistSidebarState = (state) => {
    try {
      localStorage.setItem(key, state);
    } catch {
      // Storage can be blocked by browser policy; interaction remains available.
    }
  };
  const setCollapsed = (collapsed) => {
    shell.dataset.sidebarState = collapsed ? 'collapsed' : 'expanded';
    desktopToggle?.setAttribute('aria-expanded', String(!collapsed));
    desktopToggle?.setAttribute('aria-label', collapsed ? '展开侧栏' : '折叠侧栏');
    persistSidebarState(collapsed ? 'collapsed' : 'expanded');
  };
  const closeDrawer = () => {
    const wasOpen = shell.classList.contains('nav-open');
    shell.classList.remove('nav-open');
    mobileToggle?.setAttribute('aria-expanded', 'false');
    if (backdrop) backdrop.hidden = true;
    appMain?.removeAttribute('inert');
    if (wasOpen) mobileToggle?.focus();
  };
  const drawerFocusables = () => Array.from(sidebar.querySelectorAll('a, button:not([disabled]), input:not([disabled])'))
    .filter((element) => element.getClientRects().length > 0);
  setCollapsed(readSidebarState() === 'collapsed');
  desktopToggle?.addEventListener('click', () => setCollapsed(shell.dataset.sidebarState !== 'collapsed'));
  mobileToggle?.addEventListener('click', () => {
    shell.classList.add('nav-open');
    mobileToggle.setAttribute('aria-expanded', 'true');
    if (backdrop) backdrop.hidden = false;
    appMain?.setAttribute('inert', '');
    const currentLink = sidebar.querySelector('[aria-current="page"]');
    (currentLink || drawerFocusables()[0])?.focus();
  });
  backdrop?.addEventListener('click', closeDrawer);
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') closeDrawer();
    if (event.key !== 'Tab' || !shell.classList.contains('nav-open')) return;
    const focusables = drawerFocusables();
    if (!focusables.length) return;
    const first = focusables[0];
    const last = focusables[focusables.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  });
  sidebar.querySelectorAll('a').forEach((link) => link.addEventListener('click', closeDrawer));
})();
