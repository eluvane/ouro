import assert from 'node:assert/strict';
import { afterEach, beforeEach, test } from 'node:test';
import { JSDOM } from 'jsdom';
import { TypePlay } from '../src/type-play.js';
import { snake_path, snake_point, advance_snake_path } from '../src/type-snake-path.js';

let dom, root, play, frames, clock, captured, letters;

function seeded_random(seed) {
  return () => {
    seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
    return seed / 4294967296;
  };
}

function rect(x, y, width, height) {
  return { x, y, left: x, top: y, right: x + width, bottom: y + height, width, height };
}

beforeEach(() => {
  dom = new JSDOM('<main><h1>Learn Ouro.<br>Build something real.</h1></main>', { pretendToBeVisual: true });
  root = dom.window.document.querySelector('main');
  root.getBoundingClientRect = () => rect(0, 64, 1000, 700);
  frames = new Map();
  clock = 0;
  let frame_id = 0;
  dom.window.requestAnimationFrame = callback => { frames.set(++frame_id, callback); return frame_id; };
  dom.window.cancelAnimationFrame = id => frames.delete(id);
  dom.window.matchMedia = () => ({ matches: false });
  dom.window.Math = Object.create(Math);
  dom.window.Math.random = seeded_random(42);
  captured = new Set();
  root.setPointerCapture = id => captured.add(id);
  root.hasPointerCapture = id => captured.has(id);
  root.releasePointerCapture = id => captured.delete(id);
  play = new TypePlay(root);
  letters = [...root.querySelectorAll('.type-letter')];
  let base_x = 230;
  for (const word of root.querySelectorAll('.type-word')) {
    const origin_x = base_x;
    const characters = [...word.children];
    word.getBoundingClientRect = () => {
      const p = play.positions.get(word);
      return rect(origin_x + p.x, 364 + p.y, characters.length * 16, 32);
    };
    characters.forEach((letter, index) => {
      letter.getBoundingClientRect = () => {
        const w = play.positions.get(word);
        const p = play.positions.get(letter);
        return rect(origin_x + index * 16 + w.x + p.x, 364 + w.y + p.y, 16, 32);
      };
    });
    base_x += characters.length * 16 + 20;
  }
});

afterEach(() => {
  play.stop();
  dom.window.close();
});

function pointer(element, type, x, y, extra = {}) {
  const event = new dom.window.MouseEvent(type, { clientX: x, clientY: y, bubbles: true, cancelable: true, ...extra });
  Object.defineProperties(event, {
    pointerId: { value: 1 }, pointerType: { value: 'mouse' }, isPrimary: { value: true },
  });
  element.dispatchEvent(event);
}

function drag(letter, dx, dy, extra = {}) {
  const r = letter.getBoundingClientRect();
  const x = r.left + r.width / 2;
  const y = r.top + r.height / 2;
  pointer(letter, 'pointerdown', x, y, extra);
  pointer(root, 'pointermove', x + dx, y + dy, extra);
  pointer(root, 'pointerup', x + dx, y + dy, extra);
}

function advance(seconds) {
  for (let step = 0; step < Math.ceil(seconds * 60); step++) {
    clock += 1000 / 60;
    const pending = [...frames.values()];
    frames.clear();
    for (const callback of pending) callback(clock);
  }
}

function start_snake() {
  for (const letter of letters.slice(0, 7)) drag(letter, 0, 16);
  advance(2);
  assert.equal(play.snake.running, true);
  assert.equal(root.classList.contains('is-snake'), true);
}

test('letters retain their drop position; Escape, resize and cancellation do not reset them', () => {
  drag(letters[0], 70, 50);
  assert.deepEqual(play.positions.get(letters[0]), { x: 70, y: 50 });
  assert.deepEqual(play.positions.get(letters[1]), { x: 0, y: 0 });
  assert.equal(root.querySelector('h1').getAttribute('aria-label'), 'Learn Ouro. Build something real.');
  assert.equal(root.querySelector('[aria-describedby], .type-play__help, .type-play__reset'), null);
  letters[0].dispatchEvent(new dom.window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  dom.window.dispatchEvent(new dom.window.Event('resize'));
  advance(1);
  assert.deepEqual(play.positions.get(letters[0]), { x: 70, y: 50 });
  const r = letters[0].getBoundingClientRect();
  pointer(letters[0], 'pointerdown', r.x, r.y);
  pointer(root, 'pointermove', r.x + 20, r.y + 10);
  pointer(root, 'pointercancel', r.x + 20, r.y + 10);
  assert.deepEqual(play.positions.get(letters[0]), { x: 90, y: 60 });
  assert.equal(play.active, null);
  assert.equal(captured.size, 0);
});

test('repeated drags of one letter do not trigger a train; seven distinct letters do', () => {
  for (let i = 0; i < 10; i++) drag(letters[0], 0, 5);
  assert.equal(play.snake.running, false);
  for (const letter of letters.slice(1, 6)) drag(letter, 0, 16);
  assert.equal(play.snake.running, false);
  drag(letters[6], 0, 16);
  assert.equal(root.classList.contains('is-panicking'), true);
  advance(2);
  assert.equal(play.snake.chain.length, letters.length);
  const before = { ...play.positions.get(letters[0]) };
  advance(0.2);
  assert.notDeepEqual(play.positions.get(letters[0]), before);
});

test('stealing a letter keeps the train running and closes its gap; a nearby drop rejoins smoothly', () => {
  start_snake();
  const snake = play.snake;
  const stolen = snake.chain[3];
  const following = snake.chain[4];
  const old_gap = following.distance;
  const head = snake.chain[0];
  const old_head = { x: head.x, y: head.y };
  const r = stolen.element.getBoundingClientRect();
  pointer(stolen.element, 'pointerdown', r.x + 8, r.y + 16);
  pointer(root, 'pointermove', 20, 84);
  const held_position = { ...play.positions.get(stolen.element) };
  advance(0.8);
  assert.equal(snake.running, true);
  assert.equal(snake.chain.length, letters.length - 1);
  assert.ok(following.distance < old_gap - 10);
  assert.notDeepEqual({ x: head.x, y: head.y }, old_head);
  assert.deepEqual(play.positions.get(stolen.element), held_position);
  pointer(root, 'pointerup', 20, 84);
  advance(0.6);
  assert.deepEqual(play.positions.get(stolen.element), held_position);
  const parked = stolen.element.getBoundingClientRect();
  drag(stolen.element, head.x - parked.x - 8, head.y + 64 - parked.y - 16);
  const drop = { ...play.positions.get(stolen.element) };
  assert.equal(snake.detached.has(stolen), false);
  assert.equal(snake.chain.length, letters.length);
  assert.equal(snake.chain[1], stolen);
  advance(1 / 60);
  const next = play.positions.get(stolen.element);
  const first_step = Math.hypot(next.x - drop.x, next.y - drop.y);
  assert.ok(first_step > 0 && first_step < 100);
  advance(0.5);
  const target = snake_point(snake.path, snake.path.head - stolen.distance);
  assert.ok(Math.hypot(stolen.x - target.x, stolen.y - target.y) < 1);
});

test('Shift extracts the entire word without stopping the rest of the train', () => {
  start_snake();
  const word = letters[0].closest('.type-word');
  const r = letters[0].getBoundingClientRect();
  pointer(letters[0], 'pointerdown', r.x + 8, r.y + 16, { shiftKey: true });
  pointer(root, 'pointermove', r.x - 12, r.y - 4, { shiftKey: true });
  assert.equal(play.snake.running, true);
  assert.equal(play.snake.detached.size, word.children.length);
  assert.equal(play.snake.chain.length, letters.length - word.children.length);
  assert.ok([...play.snake.detached].every(item => item.held));
});

test('a letter beside the route rejoins locally and immediately while the existing chain keeps moving', () => {
  start_snake();
  const snake = play.snake;
  const stolen = snake.chain[3];
  const r = stolen.element.getBoundingClientRect();
  pointer(stolen.element, 'pointerdown', r.x + 8, r.y + 16);
  let nearby;
  for (const part of snake.chain) {
    const point = snake_point(snake.path, snake.path.head - part.distance);
    const angle = (point.angle + 90) * Math.PI / 180;
    for (const sign of [-1, 1]) {
      const candidate = { x: part.x + Math.cos(angle) * sign * 95, y: part.y + Math.sin(angle) * sign * 95 };
      const gap = Math.min(...snake.chain.map(item => Math.hypot(item.x - candidate.x, item.y - candidate.y)));
      if (gap > 70 && gap < 120 && candidate.x > 20 && candidate.x < 980 && candidate.y > 20 && candidate.y < 680) {
        nearby = candidate;
        break;
      }
    }
    if (nearby) break;
  }
  assert.ok(nearby, 'a drop location beside, rather than on, the route exists');
  pointer(root, 'pointermove', nearby.x, nearby.y + 64);
  const parked = { ...play.positions.get(stolen.element) };
  advance(0.1);
  assert.equal(snake.detached.has(stolen), true);
  assert.deepEqual(play.positions.get(stolen.element), parked);
  const original_order = [...snake.chain];
  const head_distance = snake.path.head;
  pointer(root, 'pointerup', nearby.x, nearby.y + 64);
  assert.equal(snake.detached.has(stolen), false);
  assert.deepEqual(snake.chain.filter(item => item !== stolen), original_order);
  assert.notEqual(snake.chain.at(-1), stolen);
  advance(1 / 60);
  assert.ok(snake.path.head > head_distance);
  assert.notDeepEqual(play.positions.get(stolen.element), parked);
  advance(0.5);
  const target = snake_point(snake.path, snake.path.head - stolen.distance);
  assert.ok(Math.hypot(stolen.x - target.x, stolen.y - target.y) < 1);
});

test('a drop on the middle enters that gap without sending any existing letter backwards', () => {
  start_snake();
  const snake = play.snake;
  const stolen = snake.chain[3];
  const r = stolen.element.getBoundingClientRect();
  pointer(stolen.element, 'pointerdown', r.x + 8, r.y + 16);
  advance(0.8);
  const original_order = [...snake.chain];
  const before = snake.chain[12], after = snake.chain[13];
  const x = (before.x + after.x) / 2, y = (before.y + after.y) / 2;
  pointer(root, 'pointermove', x, y + 64);
  pointer(root, 'pointerup', x, y + 64);
  assert.equal(snake.detached.has(stolen), false);
  assert.equal(snake.chain[13], stolen);
  assert.equal(snake.chain[12], before);
  assert.equal(snake.chain[14], after);
  assert.deepEqual(snake.chain.filter(item => item !== stolen), original_order);
  for (let frame = 0; frame < 60; frame++) {
    const offsets = original_order.map(item => snake.path.head - item.distance);
    advance(1 / 60);
    original_order.forEach((item, index) => {
      assert.ok(snake.path.head - item.distance > offsets[index], 'pickup must not stop or reverse existing letters');
    });
  }
  const target = snake_point(snake.path, snake.path.head - stolen.distance);
  assert.ok(Math.hypot(stolen.x - target.x, stolen.y - target.y) < 1);
});

test('a drop beside the tail still joins the tail', () => {
  start_snake();
  const snake = play.snake;
  const stolen = snake.chain[3];
  const tail = snake.chain.at(-1);
  const r = stolen.element.getBoundingClientRect();
  drag(stolen.element, tail.x - r.x - 8, tail.y + 64 - r.y - 16);
  assert.equal(snake.detached.has(stolen), false);
  assert.equal(snake.chain.at(-1), stolen);
});

test('hidden documents pause motion, and component disposal cancels frames and input listeners', () => {
  start_snake();
  Object.defineProperty(dom.window.document, 'hidden', { configurable: true, value: true });
  dom.window.document.dispatchEvent(new dom.window.Event('visibilitychange'));
  assert.equal(frames.size, 0);
  const before = { ...play.positions.get(letters[0]) };
  advance(1);
  assert.deepEqual(play.positions.get(letters[0]), before);
  Object.defineProperty(dom.window.document, 'hidden', { configurable: true, value: false });
  dom.window.document.dispatchEvent(new dom.window.Event('visibilitychange'));
  advance(0.2);
  assert.notDeepEqual(play.positions.get(letters[0]), before);
  play.stop();
  assert.equal(frames.size, 0);
  const stopped = { ...play.positions.get(letters[0]) };
  drag(letters[0], 100, 100);
  assert.deepEqual(play.positions.get(letters[0]), stopped);
});

test('reduced motion keeps manual dragging and omits the autonomous effect', () => {
  dom.window.matchMedia = () => ({ matches: true });
  for (const letter of letters.slice(0, 7)) drag(letter, 0, 16);
  assert.equal(play.snake.running, false);
  assert.equal(frames.size, 0);
  assert.deepEqual(play.positions.get(letters[0]), { x: 0, y: 16 });
});

test('random routes stay in bounds, extend smoothly and retain the head trail for the body', () => {
  for (const [width, height] of [[320, 676], [1280, 836], [80, 60]]) {
    const path = snake_path(width, height, 44, { random: seeded_random(42) });
    const original_length = path.length;
    let previous = snake_point(path, path.head);
    for (let i = 0; i < 5400; i++) {
      advance_snake_path(path, 1 / 60);
      const point = snake_point(path, path.head);
      assert.ok(Number.isFinite(point.x) && Number.isFinite(point.y));
      assert.ok(point.x >= 0 && point.x <= width && point.y >= 0 && point.y <= height);
      assert.ok(Math.hypot(point.x - previous.x, point.y - previous.y) < 4);
      previous = point;
    }
    if (original_length > 0) {
      assert.ok(path.length > original_length * 2);
    }
    assert.ok(path.points.length < 1400);
    const distance = path.head;
    const remembered = snake_point(path, distance);
    for (let i = 0; i < 120; i++) advance_snake_path(path, 1 / 60);
    assert.deepEqual(snake_point(path, distance), remembered);
  }
});

test('different random seeds produce different paths, while a fixed seed stays reproducible', () => {
  const first = snake_path(1000, 700, 44, { random: seeded_random(7) });
  const second = snake_path(1000, 700, 44, { random: seeded_random(8) });
  const repeat = snake_path(1000, 700, 44, { random: seeded_random(7) });
  assert.notDeepEqual(first.points, second.points);
  assert.deepEqual(first.points, repeat.points);
});

test('random targets and wall turns obey the minimum turning radius without sharp corners', () => {
  for (const [width, height, radius] of [[1280, 836, 100], [320, 676, 58]]) {
    for (const seed of [7, 8, 42, 99, 137]) {
      const path = snake_path(width, height, 44, { random: seeded_random(seed) });
      for (let pass = 0; pass < 6; pass++) {
        for (let i = 2; i < path.points.length; i++) {
          const a = path.points[i - 2], b = path.points[i - 1], c = path.points[i];
          const first = Math.atan2(b.y - a.y, b.x - a.x);
          const second = Math.atan2(c.y - b.y, c.x - b.x);
          const turn = Math.abs(Math.atan2(Math.sin(second - first), Math.cos(second - first)));
          const step = (Math.hypot(b.x - a.x, b.y - a.y) + Math.hypot(c.x - b.x, c.y - b.y)) / 2;
          assert.ok(turn <= step / radius * 1.01, `sharp corner for seed ${seed} at ${width}px`);
          assert.ok(c.x >= 44 - 0.001 && c.x <= width - 44 + 0.001);
          assert.ok(c.y >= 44 - 0.001 && c.y <= height - 44 + 0.001);
        }
        for (let frame = 0; frame < 600; frame++) advance_snake_path(path, 1 / 60);
      }
    }
  }
});

test('letter rotation takes the short turn across the angle boundary', () => {
  start_snake();
  let previous = play.snake.items.map(item => item.angle);
  for (let frame = 0; frame < 720; frame++) {
    advance(1 / 60);
    play.snake.items.forEach((item, index) => {
      assert.ok(Math.abs(item.angle - previous[index]) < 8, 'a letter must not spin a full turn');
    });
    previous = play.snake.items.map(item => item.angle);
  }
});
