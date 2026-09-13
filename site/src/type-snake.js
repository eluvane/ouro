import { snake_path, snake_point, advance_snake_path } from './type-snake-path.js';

const DISTURBED_LETTERS = 7;
const PANIC_SECONDS = 0.42;
const GATHER_SECONDS = 0.9;
const MAX_FRAME_SECONDS = 0.05;
const MILLISECONDS = 1000;
const HALF = 0.5;
const GLYPH_SCALE = 0.75;
const LETTER_GAP = 8;
const EDGE_GAP = 24;
const EASE_POWER = 3;
const SPACING_RATE = 10;
const PICKUP_RADIUS = 120;
const PICKUP_EPSILON = 0.001;
const PICKUP_SPEED = 1800;
const MIN_PICKUP_SECONDS = 0.18;
const MAX_PICKUP_SECONDS = 0.5;
const FULL_TURN_DEGREES = 360;
const HALF_TURN_DEGREES = 180;
const LETTER = /\p{L}/u;

class TypeSnake {
  constructor(play) {
    this.play = play;
    this.changed = new Set();
    this.running = false;
    this.frame = null;
    this.letters = [...play.root.querySelectorAll('.type-letter')];
    const options = { signal: play.controller.signal };
    play.root.ownerDocument.addEventListener('visibilitychange', () => {
      play.view.cancelAnimationFrame(this.frame);
      this.last_time = null;
      if (this.running && !play.root.ownerDocument.hidden) {
        this.frame = play.view.requestAnimationFrame((time) => this.tick(time));
      }
    }, options);
    play.view.addEventListener('resize', () => this.stop(), options);
  }

  disturb(element) {
    if (this.running) {
      return;
    }
    let letters = element.querySelectorAll('.type-letter');
    if (element.matches('.type-letter')) {
      letters = [element];
    }
    for (const letter of letters) {
      if (LETTER.test(letter.textContent)) {
        this.changed.add(letter);
      }
    }
    if (this.changed.size >= DISTURBED_LETTERS && !this.running) {
      this.changed.clear();
      if (!this.play.view.matchMedia('(prefers-reduced-motion: reduce)').matches) {
        this.start();
      }
    }
  }

  start() {
    const { root, view, positions } = this.play;
    const area = root.getBoundingClientRect();
    let distance = 0;
    let previous_width = 0;
    this.items = this.letters.map((element, index) => {
      const rect = element.getBoundingClientRect();
      const position = positions.get(element);
      const x = rect.left + rect.width * HALF - area.left;
      const y = rect.top + rect.height * HALF - area.top;
      if (index > 0) {
        distance += (previous_width + rect.width) * HALF * GLYPH_SCALE + LETTER_GAP;
      }
      previous_width = rect.width;
      element.style.setProperty('--snake-index', String(index));
      return {
        element, x, y, from_x: x, from_y: y,
        base_x: x - position.x, base_y: y - position.y,
        distance, width: rect.width, size: Math.max(rect.width, rect.height),
        joined_at: PANIC_SECONDS, join_duration: GATHER_SECONDS, held: false,
      };
    });
    const inset = Math.max(...this.items.map((item) => item.size)) * HALF + EDGE_GAP;
    this.path = snake_path(area.width, area.height, inset, { trail: distance, random: view.Math.random });
    this.chain = [...this.items];
    this.detached = new Set();
    this.elapsed = 0;
    this.last_time = null;
    this.running = true;
    root.classList.add('is-panicking');
    this.frame = view.requestAnimationFrame((time) => this.tick(time));
  }

  grab(element) {
    if (!this.running) {
      return;
    }
    for (const item of this.items) {
      if (element.contains(item.element)) {
        item.held = true;
        this.detached.add(item);
        item.element.classList.add('is-detached');
      }
    }
    this.chain = this.chain.filter((item) => !this.detached.has(item));
  }

  release() {
    if (!this.running) {
      return;
    }
    const area = this.play.root.getBoundingClientRect();
    for (const item of this.detached) {
      if (item.held) {
        const rect = item.element.getBoundingClientRect();
        const position = this.play.positions.get(item.element);
        item.x = rect.left + rect.width * HALF - area.left;
        item.y = rect.top + rect.height * HALF - area.top;
        item.base_x = item.x - position.x;
        item.base_y = item.y - position.y;
        item.held = false;
      }
    }
    if (this.elapsed >= PANIC_SECONDS) {
      this.collect_nearby(snake_point(this.path, this.path.head));
    }
  }

  collect_nearby(head) {
    for (const item of this.detached) {
      if (!item.held) {
        const slot = this.pickup_slot(item, head);
        if (slot.separation < PICKUP_RADIUS) {
          item.distance = slot.distance;
          const target = snake_point(this.path, this.path.head - item.distance);
          const flight = Math.hypot(item.x - target.x, item.y - target.y) / PICKUP_SPEED;
          item.from_x = item.x;
          item.from_y = item.y;
          item.joined_at = this.elapsed;
          item.join_duration = Math.max(MIN_PICKUP_SECONDS, Math.min(MAX_PICKUP_SECONDS, flight));
          this.chain.splice(slot.index, 0, item);
          this.detached.delete(item);
          item.element.classList.remove('is-detached');
        }
      }
    }
  }

  pickup_slot(item, head) {
    const tail = this.chain.at(-1);
    if (!tail) {
      return { index: 0, distance: 0, separation: Math.hypot(item.x - head.x, item.y - head.y) };
    }
    let nearest = {
      index: this.chain.length,
      distance: tail.distance + (tail.width + item.width) * HALF * GLYPH_SCALE + LETTER_GAP,
      separation: Math.hypot(item.x - tail.x, item.y - tail.y),
    };
    for (let index = 1; index < this.chain.length; index += 1) {
      const before = this.chain[index - 1];
      const after = this.chain[index];
      const dx = after.x - before.x;
      const dy = after.y - before.y;
      const length_squared = dx * dx + dy * dy;
      let mix = 0;
      if (length_squared > 0) {
        mix = Math.max(0, Math.min(1, ((item.x - before.x) * dx + (item.y - before.y) * dy) / length_squared));
      }
      const separation = Math.hypot(item.x - before.x - dx * mix, item.y - before.y - dy * mix);
      if (separation < nearest.separation - PICKUP_EPSILON) {
        nearest = { index, distance: (before.distance + after.distance) * HALF, separation };
      }
    }
    return nearest;
  }

  tick(time) {
    if (!this.running) {
      return;
    }
    let delta = 0;
    if (this.last_time !== null) {
      delta = Math.min(MAX_FRAME_SECONDS, (time - this.last_time) / MILLISECONDS);
      this.elapsed += delta;
    }
    this.last_time = time;
    if (this.elapsed >= PANIC_SECONDS) {
      advance_snake_path(this.path, delta);
      this.play.root.classList.remove('is-panicking');
      this.play.root.classList.add('is-snake');
      let distance = 0;
      let previous = null;
      for (const item of this.chain) {
        if (previous) {
          distance += (previous.width + item.width) * HALF * GLYPH_SCALE + LETTER_GAP;
        }
        const adjustment = (distance - item.distance) * (1 - Math.exp(-SPACING_RATE * delta));
        // Open room for a pickup while every existing letter keeps moving forward.
        item.distance += Math.min(adjustment, this.path.speed * delta * HALF);
        const mix = 1 - (1 - Math.min(1, (this.elapsed - item.joined_at) / item.join_duration)) ** EASE_POWER;
        const point = snake_point(this.path, this.path.head - item.distance);
        item.x = item.from_x + (point.x - item.from_x) * mix;
        item.y = item.from_y + (point.y - item.from_y) * mix;
        this.play.place(item.element, item.x - item.base_x, item.y - item.base_y);
        const previous_angle = item.angle ?? point.angle;
        const turn = ((point.angle - previous_angle) % FULL_TURN_DEGREES + FULL_TURN_DEGREES + HALF_TURN_DEGREES) % FULL_TURN_DEGREES - HALF_TURN_DEGREES;
        item.angle = previous_angle + turn;
        item.element.style.setProperty('--snake-angle', `${item.angle}deg`);
        previous = item;
      }
      this.collect_nearby(snake_point(this.path, this.path.head));
    }
    this.frame = this.play.view.requestAnimationFrame((next_time) => this.tick(next_time));
  }

  stop() {
    this.play.view.cancelAnimationFrame(this.frame);
    this.frame = null;
    this.running = false;
    this.play.root.classList.remove('is-panicking', 'is-snake');
    for (const element of this.letters) {
      element.classList.remove('is-detached');
    }
  }
}

export { TypeSnake };
