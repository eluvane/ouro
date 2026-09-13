import { TypeSnake } from './type-snake.js';

const HOLD_DELAY_MS = 350;
const DRAG_THRESHOLD_PX = 4;
const KEY_STEP_PX = 12;
const EDGE_INSET_PX = 8;
const WORD_PARTS = /(?<space>\s+)/u;
const ARROW_STEPS = new Map([
  ['ArrowLeft', [-KEY_STEP_PX, 0]], ['ArrowRight', [KEY_STEP_PX, 0]],
  ['ArrowUp', [0, -KEY_STEP_PX]], ['ArrowDown', [0, KEY_STEP_PX]],
]);

class TypePlay {
  constructor(root) {
    this.root = root;
    this.view = root.ownerDocument.defaultView;
    this.positions = new Map();
    this.active = null;
    this.hold_timer = null;
    this.controller = new this.view.AbortController();
    this.prepare_text();
    this.snake = new TypeSnake(this);
    const options = { signal: this.controller.signal };
    root.addEventListener('pointerdown', (event) => this.start_drag(event), options);
    root.addEventListener('pointermove', (event) => this.move_drag(event), options);
    root.addEventListener('pointerup', (event) => this.end_drag(event), options);
    root.addEventListener('pointercancel', (event) => this.end_drag(event), options);
    root.addEventListener('lostpointercapture', (event) => this.end_drag(event), options);
    root.addEventListener('keydown', (event) => this.move_key(event), options);
    root.addEventListener('contextmenu', (event) => {
      if (event.target.closest('.type-word')) {
        event.preventDefault();
      }
    }, options);
    this.view.addEventListener('blur', () => this.end_drag(), options);
    root.classList.add('type-play');
  }

  prepare_text() {
    const heading = this.root.querySelector('h1');
    const doc = this.root.ownerDocument;
    const label = [...heading.childNodes].map((node) => {
      if (node.nodeName === 'BR') {
        return ' ';
      }
      return node.textContent;
    }).join('');
    heading.setAttribute('aria-label', label);
    const text_nodes = [...heading.childNodes].filter((node) => node.nodeType === this.view.Node.TEXT_NODE);
    for (const node of text_nodes) {
      const fragment = doc.createDocumentFragment();
      for (const text of node.textContent.split(WORD_PARTS)) {
        if (text.trim()) {
          const word = doc.createElement('span');
          word.className = 'type-word';
          this.positions.set(word, { x: 0, y: 0 });
          for (const character of text) {
            const letter = doc.createElement('button');
            letter.type = 'button';
            letter.className = 'type-letter';
            letter.setAttribute('aria-label', `Move ${character} in ${text}`);
            const glyph = doc.createElement('span');
            glyph.textContent = character;
            letter.append(glyph);
            word.append(letter);
            this.positions.set(letter, { x: 0, y: 0 });
          }
          fragment.append(word);
        } else {
          fragment.append(doc.createTextNode(text));
        }
      }
      node.replaceWith(fragment);
    }
  }

  place(element, x, y) {
    this.positions.set(element, { x, y });
    element.style.setProperty('--drag-x', `${x}px`);
    element.style.setProperty('--drag-y', `${y}px`);
  }

  select_target(element) {
    this.active.element?.classList.remove('is-grabbed');
    this.snake.grab(element);
    this.active.element = element;
    this.active.position = this.positions.get(element);
    const rectangles = [element.getBoundingClientRect()];
    for (const letter of element.querySelectorAll('.type-letter')) {
      rectangles.push(letter.getBoundingClientRect());
    }
    this.active.bounds = {
      left: Math.min(...rectangles.map((rect) => rect.left)),
      right: Math.max(...rectangles.map((rect) => rect.right)),
      top: Math.min(...rectangles.map((rect) => rect.top)),
      bottom: Math.max(...rectangles.map((rect) => rect.bottom)),
    };
    element.classList.add('is-grabbed');
    element.closest('.type-word').classList.add('is-lifted');
  }

  start_drag(event) {
    const letter = event.target.closest('.type-letter');
    if (!letter || event.button !== 0 || event.isPrimary === false || this.active) {
      return;
    }
    event.preventDefault();
    this.active = { id: event.pointerId, start_x: event.clientX, start_y: event.clientY, moved: false };
    const word = letter.closest('.type-word');
    let target = letter;
    if (event.shiftKey) {
      target = word;
    }
    this.select_target(target);
    this.root.querySelector('.type-letter:focus')?.blur();
    this.root.classList.add('is-dragging');
    this.root.setPointerCapture(event.pointerId);
    if (event.pointerType === 'touch' && !event.shiftKey) {
      this.hold_timer = this.view.setTimeout(() => this.select_target(word), HOLD_DELAY_MS);
    }
  }

  constrain(bounds, dx, dy) {
    const area = this.root.getBoundingClientRect();
    const min_x = area.left + EDGE_INSET_PX - bounds.left;
    const max_x = area.right - EDGE_INSET_PX - bounds.right;
    const min_y = area.top + EDGE_INSET_PX - bounds.top;
    const max_y = area.bottom - EDGE_INSET_PX - bounds.bottom;
    return {
      x: Math.min(max_x, Math.max(min_x, dx)),
      y: Math.min(max_y, Math.max(min_y, dy)),
    };
  }

  move_drag(event) {
    const drag = this.active;
    if (!drag || event.pointerId !== drag.id) {
      return;
    }
    const dx = event.clientX - drag.start_x;
    const dy = event.clientY - drag.start_y;
    if (!drag.moved && Math.hypot(dx, dy) < DRAG_THRESHOLD_PX) {
      return;
    }
    drag.moved = true;
    this.view.clearTimeout(this.hold_timer);
    const delta = this.constrain(drag.bounds, dx, dy);
    this.place(drag.element, drag.position.x + delta.x, drag.position.y + delta.y);
  }

  end_drag(event) {
    const drag = this.active;
    if (!drag || (event && event.pointerId !== drag.id)) {
      return;
    }
    this.active = null;
    this.view.clearTimeout(this.hold_timer);
    drag.element.classList.remove('is-grabbed');
    drag.element.closest('.type-word').classList.remove('is-lifted');
    this.root.classList.remove('is-dragging');
    if (this.root.hasPointerCapture(drag.id)) {
      this.root.releasePointerCapture(drag.id);
    }
    this.snake.release();
    if (drag.moved && event?.type === 'pointerup') {
      this.snake.disturb(drag.element);
    }
  }

  move_key(event) {
    const letter = event.target.closest('.type-letter');
    const steps = ARROW_STEPS.get(event.key);
    if (!(letter && steps) || event.ctrlKey || event.metaKey || event.altKey || this.active) {
      return;
    }
    event.preventDefault();
    let element = letter;
    if (event.shiftKey) {
      element = letter.closest('.type-word');
    }
    this.active = {};
    this.select_target(element);
    const { position, bounds } = this.active;
    const delta = this.constrain(bounds, ...steps);
    this.place(element, position.x + delta.x, position.y + delta.y);
    element.classList.remove('is-grabbed');
    element.closest('.type-word').classList.remove('is-lifted');
    this.active = null;
    this.snake.release();
    this.snake.disturb(element);
  }

  stop() {
    this.end_drag();
    this.snake.stop();
    this.controller.abort();
  }
}

export { TypePlay };
