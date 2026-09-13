import assert from 'node:assert/strict';
import { afterEach, beforeEach, test } from 'node:test';
import { JSDOM } from 'jsdom';
import { copy_text, highlight_code, highlight_search } from '../src/docs-enhancements.js';

let dom;
const original_navigator = Object.getOwnPropertyDescriptor(globalThis, 'navigator');

beforeEach(() => {
  dom = new JSDOM('<!doctype html><body></body>');
  globalThis.document = dom.window.document;
  globalThis.NodeFilter = dom.window.NodeFilter;
  Object.defineProperty(globalThis, 'navigator', {
    configurable: true,
    value: dom.window.navigator,
  });
});

afterEach(() => {
  dom.window.close();
  delete globalThis.document;
  delete globalThis.NodeFilter;
  if (original_navigator) {
    Object.defineProperty(globalThis, 'navigator', original_navigator);
  } else {
    delete globalThis.navigator;
  }
});

test('Ouro highlighting preserves source and keeps HTML, quotes and comments inert', () => {
  const source = 'def message : String := "<img src=x onerror=alert(1)> -- text";\n-- def ignored : Nat := 3;\ndef n : Nat := 2;';
  const code = document.createElement('code');
  code.textContent = source;
  highlight_code(code, 'ouro');
  assert.equal(code.textContent, source);
  assert.equal(code.querySelector('img'), null);
  assert.deepEqual([...code.querySelectorAll('.syntax-keyword')].map(el => el.textContent), ['def', 'def']);
  assert.equal(code.querySelector('.syntax-string').textContent, '"<img src=x onerror=alert(1)> -- text"');
  assert.equal(code.querySelector('.syntax-comment').textContent, '-- def ignored : Nat := 3;');
  assert.equal(code.querySelector('.syntax-number').textContent, '2');
});

test('terminal flags are highlighted as options rather than Ouro comments', () => {
  const code = document.createElement('code');
  code.textContent = "sh scripts/ouro1.sh eval --eval 'add four two'\n# a comment";
  const source = code.textContent;
  highlight_code(code, 'terminal');
  assert.equal(code.textContent, source);
  assert.equal(code.querySelector('.syntax-option').textContent, '--eval');
  assert.equal(code.querySelector('.syntax-comment').textContent, '# a comment');
  assert.equal(code.querySelector('.syntax-string').textContent, "'add four two'");
});

test('search spans syntax tokens and inline markup, then restores the original source', () => {
  const section = document.createElement('section');
  section.innerHTML = '<h2>Example<a data-search-ignore>#</a></h2><p>A <code>Nat</code> value.</p><pre><code>def n : Nat := 2;</code></pre>';
  const code = section.querySelector('pre code');
  highlight_code(code, 'ouro');
  const source = section.textContent;
  const original_markup = code.innerHTML;
  highlight_search(section, 'Nat := 2');
  assert.equal([...code.querySelectorAll('mark')].map(el => el.textContent).join(''), 'Nat := 2');
  highlight_search(section, 'A Nat');
  assert.equal([...section.querySelectorAll('p mark')].map(el => el.textContent).join(''), 'A Nat');
  assert.equal(code.innerHTML, original_markup);
  highlight_search(section, '#');
  assert.equal(section.querySelector('mark'), null);
  highlight_search(section, '');
  assert.equal(section.textContent, source);
  assert.equal(code.innerHTML, original_markup);
});

test('search is literal, case insensitive and safe for HTML-looking input', () => {
  const section = document.createElement('section');
  const paragraph = document.createElement('p');
  paragraph.textContent = 'Nat NAT nat .* [a] <img src=x> İ next';
  section.append(paragraph);
  for (const query of ['.*', '[a]', '<img src=x>', 'next']) {
    highlight_search(section, query);
    assert.equal(section.querySelectorAll('mark').length, 1);
    assert.equal(section.querySelector('mark').textContent, query);
  }
  highlight_search(section, 'nat');
  assert.equal(section.querySelectorAll('mark').length, 3);
  assert.equal(section.querySelector('img'), null);
  highlight_search(section, 'missing');
  assert.equal(section.querySelector('mark'), null);
});

test('clipboard API receives exact source and rejected writes remain failures', async () => {
  let copied;
  navigator.clipboard = { writeText: async text => { copied = text; } };
  await copy_text('def n : Nat := 2;\n');
  assert.equal(copied, 'def n : Nat := 2;\n');
  navigator.clipboard.writeText = async () => { throw new Error('denied'); };
  await assert.rejects(copy_text('source'), /denied/);
  assert.equal(document.querySelector('textarea'), null);
});

test('legacy clipboard checks success, removes temporary input and restores focus and selection', async () => {
  document.body.innerHTML = '<button>Copy</button><p>Original selection</p>';
  const button = document.querySelector('button');
  button.focus();
  const selection = document.getSelection();
  const range = document.createRange();
  range.selectNodeContents(document.querySelector('p'));
  selection.removeAllRanges();
  selection.addRange(range);
  assert.equal(selection.toString(), 'Original selection');
  document.execCommand = command => {
    assert.equal(command, 'copy');
    assert.equal(document.querySelector('textarea').value, 'source');
    return true;
  };
  await copy_text('source');
  assert.equal(document.activeElement, button);
  assert.equal(selection.toString(), 'Original selection');
  assert.equal(document.querySelector('textarea'), null);
  document.execCommand = () => false;
  await assert.rejects(copy_text('source'), /could not copy/);
  assert.equal(document.activeElement, button);
  assert.equal(document.querySelector('textarea'), null);
});
