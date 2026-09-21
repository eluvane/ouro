// biome-ignore lint/nursery/noRestrictedDependencies: JQHTML boots through jQuery
// biome-ignore lint/style/useNamingConvention: $ is the jQuery binding JQHTML init expects
import $ from 'jquery/dist/jquery.slim.js';
import { boot, init, register } from '@jqhtml/core';

import './styles.css';
import './fonts.css';
import './icons.css';
import './docs.css';
import './docs-layout.css';
import './docs-content.css';
import './docs-code.css';
import './docs-mobile.css';

import { site_config } from './site.config.js';

const HTML_SUFFIX_RE = /\/index\.html$/u;
const TRAILING_SLASHES_RE = /\/+$/u;
const FALLBACK_FADE_DURATION_MS = 160;
const PRELOAD_IDLE_FALLBACK_MS = 1000;

let mode = 'development';
if (import.meta.env.PROD) {
  mode = 'production';
}

init($, {
  mode,
});

const page = document.documentElement;
let current_component = null;

function normalize_path(pathname) {
  const trimmed = pathname
    .replace(HTML_SUFFIX_RE, '')
    .replace(TRAILING_SLASHES_RE, '');
  if (trimmed.length === 0) {
    return '/';
  }
  return trimmed;
}

function get_component_for_path(pathname) {
  const clean_path = normalize_path(pathname);
  const clean_docs = normalize_path(site_config.docs_url);
  const clean_home = normalize_path(site_config.home_url);

  if (clean_path === clean_docs || clean_path.startsWith(`${clean_docs}/`)) {
    return 'Documentation_App';
  }
  if (clean_path === clean_home || clean_path === '' || clean_path === '/') {
    return 'Site_App';
  }
  return null;
}

const component_loaders = new Map([
  ['Documentation_App', () => import('./components/documentation_app.js')],
  ['Site_App', () => import('./components/site_app.js')],
]);

const titles = new Map([
  ['Documentation_App', 'Ouro Documentation'],
  ['Site_App', 'Ouro — dependently typed language and toolchain'],
]);

async function render_page_component(target_component, hash) {
  const loader = component_loaders.get(target_component);
  if (!loader) {
    throw new Error(`Unknown component: ${target_component}`);
  }

  const entry = await loader();
  entry.components.forEach(register);

  const title = titles.get(target_component);
  if (title) {
    document.title = title;
  }

  const old_app = document.querySelector('#app');
  if (old_app) {
    const comp = $(old_app).data('_component');
    if (comp && typeof comp.stop === 'function') {
      comp.stop();
    }
  }

  const new_app = document.createElement('div');
  new_app.id = 'app';
  new_app.className = '_Component_Init';
  new_app.dataset.componentInitName = target_component;

  if (old_app) {
    old_app.replaceWith(new_app);
  } else {
    document.body.appendChild(new_app);
  }

  await boot();
  await document.fonts.ready;
  current_component = target_component;

  if (hash) {
    const target = document.querySelector(hash);
    if (target) {
      target.scrollIntoView({ behavior: 'instant' });
      return;
    }
  }
  globalThis.scrollTo({ top: 0, left: 0, behavior: 'instant' });
}

async function transition_to(target_component, hash) {
  if (current_component === target_component) {
    if (hash) {
      const target = document.querySelector(hash);
      if (target) {
        target.scrollIntoView();
      }
    }
    return;
  }

  if (globalThis.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    await render_page_component(target_component, hash);
    return;
  }

  if (typeof document.startViewTransition === 'function') {
    const transition = document.startViewTransition(async () => {
      await render_page_component(target_component, hash);
    });
    await transition.finished;
  } else {
    const app = document.querySelector('#app');
    if (app) {
      app.style.opacity = '0';
      await new Promise((resolve) =>
        setTimeout(resolve, FALLBACK_FADE_DURATION_MS),
      );
    }
    await render_page_component(target_component, hash);
    const updated_app = document.querySelector('#app');
    if (updated_app) {
      updated_app.style.opacity = '1';
    }
  }
}

async function navigate(to_url) {
  const url = new URL(to_url, globalThis.location.href);
  const target_component = get_component_for_path(url.pathname);
  if (!target_component) {
    globalThis.location.href = to_url;
    return;
  }

  globalThis.history.pushState(null, '', to_url);
  await transition_to(target_component, url.hash);
}

document.addEventListener('click', (event) => {
  if (event.defaultPrevented) {
    return;
  }
  if (
    event.button !== 0 ||
    event.metaKey ||
    event.ctrlKey ||
    event.shiftKey ||
    event.altKey
  ) {
    return;
  }

  const anchor = event.target.closest('a');
  if (!anchor?.href) {
    return;
  }
  if (anchor.target === '_blank' || anchor.hasAttribute('download')) {
    return;
  }

  const url = new URL(anchor.href, globalThis.location.href);
  if (url.origin !== globalThis.location.origin) {
    return;
  }

  if (
    url.pathname === globalThis.location.pathname &&
    url.search === globalThis.location.search &&
    url.hash
  ) {
    return;
  }

  const target_component = get_component_for_path(url.pathname);
  if (!target_component) {
    return;
  }

  event.preventDefault();
  navigate(url.pathname + url.search + url.hash);
});

globalThis.addEventListener('popstate', () => {
  const target_component = get_component_for_path(
    globalThis.location.pathname,
  );
  if (target_component) {
    transition_to(target_component, globalThis.location.hash);
  }
});

page.classList.add('is-loading');

try {
  const initial_app = document.querySelector('#app');
  let initial_component = initial_app?.dataset.componentInitName;
  if (!initial_component) {
    initial_component =
      get_component_for_path(globalThis.location.pathname) || 'Site_App';
  }

  await render_page_component(initial_component, globalThis.location.hash);

  const preload_all = () => {
    const load_docs = component_loaders.get('Documentation_App');
    const load_site = component_loaders.get('Site_App');
    if (load_docs) {
      load_docs();
    }
    if (load_site) {
      load_site();
    }
  };

  if ('requestIdleCallback' in globalThis) {
    globalThis.requestIdleCallback(preload_all);
  } else {
    setTimeout(preload_all, PRELOAD_IDLE_FALLBACK_MS);
  }
} catch {
  const app = document.querySelector('#app');
  if (app !== null) {
    app.textContent =
      'The page could not start. Check the browser console for details.';
  }
} finally {
  page.classList.remove('is-loading');
}
