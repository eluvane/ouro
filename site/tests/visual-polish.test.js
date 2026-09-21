import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { DocumentationNavigation } from '../src/docs-navigation.js';

function fixture(mobile = true) {
  const media = new EventTarget();
  media.matches = mobile;
  const doc = { activeElement: null, defaultView: {
    matchMedia: () => media,
    CSS: { escape: id => id.replaceAll(':', '\\:') },
  } };
  const node = () => {
    const element = new EventTarget();
    const classes = new Set();
    const attributes = new Map();
    element.ownerDocument = doc;
    element.inert = false;
    element.classList = {
      contains: name => classes.has(name),
      add: name => classes.add(name),
      remove: name => classes.delete(name),
      toggle: (name, value) => value ? classes.add(name) : classes.delete(name),
    };
    element.setAttribute = (key, value) => attributes.set(key, value);
    element.getAttribute = key => attributes.get(key);
    element.hasAttribute = key => attributes.has(key);
    element.focus = options => { doc.activeElement = element; element.focus_options = options; };
    element.closest = selector => {
      if (selector === '[hidden]') return element.hidden ? element : null;
      if (selector === 'a[href]') return element.hasAttribute('href') ? element : null;
      throw new Error(`Unexpected selector: ${selector}`);
    };
    return element;
  };
  doc.documentElement = node();
  const root = node(), sidebar = node(), main = node(), backdrop = node(), toggle = node();
  const home = node(), chapter = node(), hidden = node(), target = node();
  const links = [home, chapter, hidden];
  hidden.hidden = true;
  hidden.setAttribute('aria-current', 'page');
  chapter.hash = '#introduction';
  chapter.setAttribute('href', chapter.hash);
  chapter.setAttribute('aria-current', 'page');
  sidebar.querySelectorAll = selector => {
    assert.equal(selector, 'a[href]');
    return links;
  };
  sidebar.contains = element => links.includes(element);
  const elements = new Map([
    ['.docs-sidebar', sidebar], ['.docs-main', main], ['.sidebar-backdrop', backdrop],
  ]);
  root.querySelector = selector => elements.get(selector);
  doc.querySelector = selector => selector === '#introduction' ? target : null;
  const navigation = new DocumentationNavigation(root, toggle);
  const resize = value => { media.matches = value; media.dispatchEvent(new Event('change')); };
  const key = (name, shiftKey = false) => {
    const event = new Event('keydown', { cancelable: true });
    Object.assign(event, { key: name, shiftKey, isComposing: false });
    root.dispatchEvent(event);
    return event;
  };
  return { navigation, root, sidebar, main, backdrop, toggle, home, chapter, hidden, target, doc, resize, key };
}

test('closed mobile navigation is inert; opening focuses a visible current chapter', () => {
  const f = fixture();
  assert.equal(f.sidebar.inert, true);
  assert.equal(f.main.inert, false);
  assert.equal(f.toggle.getAttribute('aria-expanded'), 'false');
  f.navigation.toggle();
  assert.equal(f.sidebar.inert, false);
  assert.equal(f.main.inert, true);
  assert.equal(f.doc.documentElement.classList.contains('docs-navigation-open'), true);
  assert.equal(f.toggle.getAttribute('aria-expanded'), 'true');
  assert.equal(f.doc.activeElement, f.chapter);
  assert.deepEqual(f.chapter.focus_options, { preventScroll: true });
  assert.equal(f.navigation.focus_targets().includes(f.hidden), false);
  f.navigation.stop();
});

test('Tab wraps inside the open drawer without swallowing ordinary tab steps', () => {
  const f = fixture();
  f.navigation.toggle();
  f.home.focus();
  assert.equal(f.key('Tab').defaultPrevented, false);
  assert.equal(f.key('Tab', true).defaultPrevented, true);
  assert.equal(f.doc.activeElement, f.backdrop);
  assert.equal(f.key('Tab').defaultPrevented, true);
  assert.equal(f.doc.activeElement, f.home);
  f.main.focus();
  assert.equal(f.key('Tab').defaultPrevented, true);
  assert.equal(f.doc.activeElement, f.home);
  f.navigation.stop();
});

test('Escape restores the opener and releases the background and scroll lock', () => {
  const f = fixture();
  f.navigation.toggle();
  assert.equal(f.key('Escape').defaultPrevented, true);
  assert.equal(f.doc.activeElement, f.toggle);
  assert.equal(f.main.inert, false);
  assert.equal(f.sidebar.inert, true);
  assert.equal(f.doc.documentElement.classList.contains('docs-navigation-open'), false);
  assert.equal(f.toggle.getAttribute('aria-expanded'), 'false');
  assert.equal(f.toggle.getAttribute('aria-label'), 'Open navigation');
  assert.equal(f.key('Tab').defaultPrevented, false);
  f.navigation.stop();
});

test('a chapter selection moves focus to its content, leaving native hash scrolling intact', () => {
  const f = fixture();
  f.navigation.toggle();
  f.navigation.close({ currentTarget: f.chapter });
  assert.equal(f.doc.activeElement, f.target);
  assert.equal(f.target.getAttribute('tabindex'), '-1');
  assert.deepEqual(f.target.focus_options, { preventScroll: true });
  assert.equal(f.navigation.is_open(), false);
  f.navigation.stop();
});

test('section IDs are escaped before the focus lookup', () => {
  const f = fixture();
  f.chapter.setAttribute('href', '#chapter:intro');
  f.doc.querySelector = selector => {
    assert.equal(selector, '#chapter\\:intro');
    return f.target;
  };
  f.navigation.toggle();
  f.navigation.close({ currentTarget: f.chapter });
  assert.equal(f.doc.activeElement, f.target);
  f.navigation.stop();
});

test('missing sections and non-fragment links restore the navigation opener', () => {
  for (const href of ['#missing', '#', '/ouro/docs/']) {
    const f = fixture();
    f.chapter.setAttribute('href', href);
    f.navigation.toggle();
    f.navigation.close({ currentTarget: f.chapter });
    assert.equal(f.doc.activeElement, f.toggle);
    f.navigation.stop();
  }
});

test('desktop/mobile crossings never leave hidden focused links or inert desktop content', () => {
  const f = fixture();
  f.navigation.toggle();
  f.resize(false);
  assert.equal(f.navigation.is_open(), false);
  assert.equal(f.sidebar.inert, false);
  assert.equal(f.main.inert, false);
  assert.equal(f.doc.documentElement.classList.contains('docs-navigation-open'), false);
  assert.equal(f.doc.activeElement, f.chapter);
  f.navigation.toggle();
  assert.equal(f.navigation.is_open(), false);
  f.resize(true);
  assert.equal(f.doc.activeElement, f.toggle);
  assert.equal(f.sidebar.inert, true);
  f.navigation.stop();
});

test('route teardown releases all state and removes keyboard and media listeners', () => {
  const f = fixture();
  f.navigation.toggle();
  f.navigation.stop();
  assert.equal(f.main.inert, false);
  assert.equal(f.sidebar.inert, false);
  assert.equal(f.doc.documentElement.classList.contains('docs-navigation-open'), false);
  assert.equal(f.root.classList.contains('navigation-open'), false);
  // Reintroducing state after disposal must not reactivate a detached owner.
  f.root.classList.add('navigation-open');
  f.resize(false);
  f.resize(true);
  assert.equal(f.root.classList.contains('navigation-open'), true);
  assert.equal(f.key('Escape').defaultPrevented, false);
});

const source = name => readFileSync(new URL(`../src/${name}`, import.meta.url), 'utf8');
const colors = Object.fromEntries([...source('styles.css').matchAll(/--([\w-]+): rgb\((\d+) (\d+) (\d+)\);/g)]
  .map(([, name, r, g, b]) => [name, [r, g, b].map(Number)]));
function luminance(rgb) {
  const linear = rgb.map(value => {
    const channel = value / 255;
    return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
  });
  return linear[0] * 0.2126 + linear[1] * 0.7152 + linear[2] * 0.0722;
}
function contrast(a, b) {
  const values = [luminance(colors[a]), luminance(colors[b])].sort((x, y) => y - x);
  return (values[0] + 0.05) / (values[1] + 0.05);
}

test('body, muted text, selected links and search highlights retain readable contrast', () => {
  for (const surface of ['bg', 'field', 'panel', 'surface-hover', 'selection']) {
    for (const text of ['text', 'muted']) {
      assert.ok(contrast(text, surface) >= 4.5, `${text} on ${surface}`);
    }
    assert.ok(contrast('accent', surface) >= 3, `focus on ${surface}`);
  }
  assert.ok(contrast('accent-text', 'accent-wash') >= 4.5);
});

test('motion and overflow fixes stay in the owning styles rather than clipping the page', () => {
  const styles = source('styles.css');
  assert.match(styles, /--viewport-height: 100vh;/);
  assert.match(styles, /@supports \(height: 100svh\) \{\s+:root \{\s+--viewport-height: 100svh;/);
  assert.equal((styles.match(/min-height: var\(--viewport-height\);/g) || []).length, 2);
  assert.match(styles, /min-height: calc\(var\(--viewport-height\) - var\(--chrome-height\)\);/);
  assert.doesNotMatch(styles, /overflow-x: hidden/);
  assert.match(styles, /scrollbar-gutter: stable/);
  assert.match(styles, /animation: none !important/);
  assert.doesNotMatch(source('docs-layout.css'), /width: 300%|--focus-x|--duration-wave/);
  assert.match(source('docs-layout.css'), /\.docs-header__search:focus-within::before \{\s+opacity: 1;/);
  assert.match(source('docs-layout.css'), /\.docs-header__search input:focus-visible \{\s+outline: none;/);
  assert.match(source('type-play.css'), /\.type-letter:focus:not\(:focus-visible\)/);
  assert.match(source('docs-mobile.css'), /--hash-size: 44px/);
});
