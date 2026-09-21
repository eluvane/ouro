const MOBILE_NAVIGATION_QUERY = '(max-width: 768px)';

// Keep the existing off-canvas navigation operable without exposing the page
// underneath it to keyboard focus or leaving scroll locked after a route change.
class DocumentationNavigation {
  constructor(root, toggle) {
    this.root = root;
    this.toggle_button = toggle;
    this.doc = root.ownerDocument;
    this.sidebar = root.querySelector('.docs-sidebar');
    this.main = root.querySelector('.docs-main');
    this.backdrop = root.querySelector('.sidebar-backdrop');
    this.media = this.doc.defaultView.matchMedia(MOBILE_NAVIGATION_QUERY);
    this.on_media_change = () => this.sync();
    this.on_keydown = (event) => this.handle_keydown(event);
    this.media.addEventListener('change', this.on_media_change);
    root.addEventListener('keydown', this.on_keydown);
    this.sync();
  }

  is_open() {
    return this.media.matches && this.root.classList.contains('navigation-open');
  }

  sync() {
    if (!this.media.matches) {
      this.root.classList.remove('navigation-open');
    }
    const open = this.is_open();
    const focus_in_sidebar = this.sidebar.contains(this.doc.activeElement);
    this.sidebar.inert = this.media.matches && !open;
    this.main.inert = open;
    this.doc.documentElement.classList.toggle('docs-navigation-open', open);
    this.toggle_button.setAttribute('aria-expanded', String(open));
    let label = 'Open navigation';
    if (open) {
      label = 'Close navigation';
    }
    this.toggle_button.setAttribute('aria-label', label);
    if (this.sidebar.inert && focus_in_sidebar) {
      this.toggle_button.focus({ preventScroll: true });
    }
  }

  focus_targets() {
    const links = [...this.sidebar.querySelectorAll('a[href]')].filter(
      (link) => !link.closest('[hidden]'),
    );
    return [...links, this.backdrop];
  }

  toggle() {
    if (!this.media.matches) {
      return;
    }
    if (this.is_open()) {
      this.close();
      return;
    }
    this.root.classList.add('navigation-open');
    this.sync();
    const targets = this.focus_targets();
    const active = targets.find((link) => link.hasAttribute('aria-current'));
    (active || targets[0]).focus({ preventScroll: true });
  }

  close(event) {
    const was_open = this.is_open();
    this.root.classList.remove('navigation-open');
    this.sync();
    if (!was_open) {
      return;
    }
    const link = event?.currentTarget?.closest('a[href]');
    const hash = link?.getAttribute('href');
    let target = null;
    if (hash?.startsWith('#') && hash.length > 1) {
      const id = this.doc.defaultView.CSS.escape(hash.slice(1));
      target = this.doc.querySelector(`#${id}`);
    }
    if (target) {
      // Preserve native fragment scrolling, including reduced-motion behavior.
      target.setAttribute('tabindex', '-1');
      target.focus({ preventScroll: true });
    } else {
      this.toggle_button.focus({ preventScroll: true });
    }
  }

  handle_keydown(event) {
    if (!this.is_open() || event.isComposing) {
      return;
    }
    if (event.key === 'Escape') {
      event.preventDefault();
      this.close();
    } else if (event.key === 'Tab') {
      const targets = this.focus_targets();
      const [first] = targets;
      const last = targets.at(-1);
      const current = this.doc.activeElement;
      if (!targets.includes(current) || (event.shiftKey && current === first)) {
        event.preventDefault();
        let target = first;
        if (event.shiftKey) {
          target = last;
        }
        target.focus();
      } else if (!event.shiftKey && current === last) {
        event.preventDefault();
        first.focus();
      }
    }
  }

  stop() {
    this.media.removeEventListener('change', this.on_media_change);
    this.root.removeEventListener('keydown', this.on_keydown);
    this.root.classList.remove('navigation-open');
    this.doc.documentElement.classList.remove('docs-navigation-open');
    this.sidebar.inert = false;
    this.main.inert = false;
    this.toggle_button.setAttribute('aria-expanded', 'false');
    this.toggle_button.setAttribute('aria-label', 'Open navigation');
  }
}

export { DocumentationNavigation };
