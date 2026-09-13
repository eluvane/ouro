// Display tokens follow the repository's Ouro syntax and editor grammar.
const OURO_TOKENS_RE = /(?<comment>--[^\r\n]*)|(?<string>"(?:\\.|[^"\\])*")|(?<keyword>\b(?:def|axiom|inductive|record|effect|import|where|match|with|end|do|handle|perform|let|in|fix|fun|as|open|intrinsic|extern|representation)\b!?)|(?<type>\b[A-Z][\w']*\b)|(?<number>\b\d+\b)|(?<operator>:=|->|=>|<-|\|>|[|:;,])/gu;
const TERMINAL_TOKENS_RE = /(?<string>"(?:\\.|[^"\\])*"|'[^']*')|(?<comment>^\s*#[^\r\n]*)|(?<keyword>^(?:git|cd|sh)\b)|(?<option>--[\w-]+)/gmu;
const REGEXP_SPECIAL_RE = /[.*+?^${}()|[\]\\]/gu;

function highlight_code(code, language) {
  let pattern = OURO_TOKENS_RE;
  if (language === 'terminal') {
    pattern = TERMINAL_TOKENS_RE;
  }
  const source = code.textContent;
  const fragment = document.createDocumentFragment();
  let offset = 0;

  for (const match of source.matchAll(pattern)) {
    fragment.append(source.slice(offset, match.index));
    const token = document.createElement('span');
    const kind = Object.keys(match.groups).find(
      (name) => match.groups[name] !== undefined,
    );
    token.className = `syntax-${kind}`;
    token.textContent = match[0];
    fragment.append(token);
    offset = match.index + match[0].length;
  }

  fragment.append(source.slice(offset));
  code.replaceChildren(fragment);
}

function mark_text_node(node, offset, matches) {
  const source = node.textContent;
  const fragment = document.createDocumentFragment();
  let cursor = 0;
  for (const match of matches) {
    const start = Math.max(0, match.index - offset);
    const end = Math.min(source.length, match.index + match[0].length - offset);
    if (start < end) {
      fragment.append(source.slice(cursor, start));
      const mark = document.createElement('mark');
      mark.dataset.searchMatch = '';
      mark.textContent = source.slice(start, end);
      fragment.append(mark);
      cursor = end;
    }
  }
  if (cursor > 0) {
    fragment.append(source.slice(cursor));
    node.replaceWith(fragment);
  }
}

function highlight_block(block, pattern) {
  const walker = document.createTreeWalker(block, NodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      if (node.parentElement.closest('[data-search-ignore]')) {
        return NodeFilter.FILTER_REJECT;
      }
      return NodeFilter.FILTER_ACCEPT;
    },
  });
  const nodes = [];
  let source = '';
  while (walker.nextNode()) {
    const node = walker.currentNode;
    nodes.push({ node, offset: source.length });
    source += node.textContent;
  }
  const matches = Array.from(source.matchAll(pattern));
  for (const { node, offset } of nodes) {
    mark_text_node(node, offset, matches);
  }
}

function highlight_search(section, query) {
  for (const mark of section.querySelectorAll('mark[data-search-match]')) {
    mark.replaceWith(document.createTextNode(mark.textContent));
  }
  section.normalize();
  if (!query) {
    return;
  }
  const pattern = new RegExp(query.replace(REGEXP_SPECIAL_RE, '\\$&'), 'giu');
  for (const block of section.querySelectorAll('h1, h2, p, pre code')) {
    highlight_block(block, pattern);
  }
}

async function copy_text(text) {
  if (globalThis.navigator?.clipboard?.writeText) {
    await globalThis.navigator.clipboard.writeText(text);
    return;
  }

  const active_element = document.activeElement;
  const selection = document.getSelection();
  const ranges = [];
  for (let index = 0; index < (selection?.rangeCount ?? 0); index += 1) {
    ranges.push(selection.getRangeAt(index).cloneRange());
  }
  const textarea = document.createElement('textarea');
  textarea.className = 'clipboard-buffer';
  textarea.value = text;
  textarea.setAttribute('aria-label', 'Text to copy');
  document.body.append(textarea);
  try {
    textarea.select();
    if (!document.execCommand('copy')) {
      throw new Error('The browser could not copy to the clipboard.');
    }
  } finally {
    textarea.remove();
    active_element?.focus({ preventScroll: true });
    selection?.removeAllRanges();
    for (const range of ranges) {
      selection?.addRange(range);
    }
  }
}

export { highlight_code, highlight_search, copy_text };
