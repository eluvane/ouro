const HALF = 0.5;
const FULL_TURN = Math.PI * 2;
const HALF_TURN_DEGREES = 180;
const DEGREES = HALF_TURN_DEGREES / Math.PI;
const PATH_STEP = 3;
const MAX_TURN_RADIUS = 100;
const TURN_RADIUS_RATIO = 0.25;
const MIN_TARGET_TRAVEL = 300;
const TARGET_TRAVEL_RANGE = 600;
const GEOMETRY_EPSILON = 0.000_001;
const TARGET_INSET = 0.12;
const TARGET_SPAN = 0.76;
const TARGET_MODES = 6;
const RIGHT_EDGE = 1;
const TOP_EDGE = 2;
const BOTTOM_EDGE = 3;
const LOOKAHEAD = 400;
const TRAIL_PADDING = 200;
const DEFAULT_TRAIL = 1000;
const MIN_SEGMENT = 0.001;
const MIN_SPEED = 110;
const SPEED_RANGE = 80;
const SPEED_EASING = 2;
const MIN_PACE_SECONDS = 3;
const PACE_RANGE_SECONDS = 4;

function target_point(path) {
  const { bounds, random } = path;
  const mode = Math.floor(random() * TARGET_MODES);
  let x = TARGET_INSET + random() * TARGET_SPAN;
  let y = TARGET_INSET + random() * TARGET_SPAN;
  if (mode === 0) {
    x = TARGET_INSET;
  } else if (mode === RIGHT_EDGE) {
    x = 1 - TARGET_INSET;
  } else if (mode === TOP_EDGE) {
    y = TARGET_INSET;
  } else if (mode === BOTTOM_EDGE) {
    y = 1 - TARGET_INSET;
  }
  return { x: bounds.left + x * bounds.width, y: bounds.top + y * bounds.height };
}

function turn_fits(path, point, heading, direction) {
  const radius = path.turn_radius;
  const x = point.x - Math.sin(heading) * radius * direction;
  const y = point.y + Math.cos(heading) * radius * direction;
  return x - radius >= path.bounds.left - GEOMETRY_EPSILON &&
    x + radius <= path.bounds.right + GEOMETRY_EPSILON &&
    y - radius >= path.bounds.top - GEOMETRY_EPSILON &&
    y + radius <= path.bounds.bottom + GEOMETRY_EPSILON;
}

function arc_step(start, heading, turn) {
  if (Math.abs(turn) < GEOMETRY_EPSILON) {
    return { x: start.x + Math.cos(heading) * PATH_STEP, y: start.y + Math.sin(heading) * PATH_STEP };
  }
  const radius = PATH_STEP / turn;
  return {
    x: start.x + radius * (Math.sin(heading + turn) - Math.sin(heading)),
    y: start.y - radius * (Math.cos(heading + turn) - Math.cos(heading)),
  };
}

function append_step(path) {
  if (path.turn_radius < MIN_SEGMENT) {
    return;
  }
  const start = path.points.at(-1);
  if (!path.target || path.length >= path.target_until || Math.hypot(path.target.x - start.x, path.target.y - start.y) < path.turn_radius) {
    path.target = target_point(path);
    path.target_until = path.length + MIN_TARGET_TRAVEL + path.random() * TARGET_TRAVEL_RANGE;
  }
  const desired = Math.atan2(path.target.y - start.y, path.target.x - start.x);
  const difference = Math.atan2(Math.sin(desired - path.heading), Math.cos(desired - path.heading));
  const limit = PATH_STEP / path.turn_radius;
  let turn = Math.max(-limit, Math.min(limit, difference));
  let next = arc_step(start, path.heading, turn);
  // Preserve room for a full-radius turn, including near corners.
  if (!(turn_fits(path, next, path.heading + turn, 1) || turn_fits(path, next, path.heading + turn, -1))) {
    turn = -limit;
    if (turn_fits(path, start, path.heading, 1)) {
      turn = limit;
    }
    next = arc_step(start, path.heading, turn);
  }
  path.heading = Math.atan2(Math.sin(path.heading + turn), Math.cos(path.heading + turn));
  path.length += PATH_STEP;
  path.points.push({ ...next, distance: path.length });
}

function extend_path(path, distance) {
  while (path.length < distance) {
    const before = path.length;
    append_step(path);
    if (path.length === before) {
      break;
    }
  }
}

function snake_path(width, height, inset, { trail = DEFAULT_TRAIL, random = Math.random } = {}) {
  const left = Math.min(inset, width * HALF);
  const top = Math.min(inset, height * HALF);
  const path = {
    bounds: { left, top, right: width - left, bottom: height - top, width: width - left * 2, height: height - top * 2 },
    points: [{ x: width * HALF, y: height * HALF, distance: 0 }],
    length: 0, head: 0, heading: random() * FULL_TURN, random,
    trail: trail + TRAIL_PADDING, speed: MIN_SPEED, target_speed: MIN_SPEED,
    pace_time: 0,
  };
  path.turn_radius = Math.min(MAX_TURN_RADIUS, path.bounds.width * TURN_RADIUS_RATIO, path.bounds.height * TURN_RADIUS_RATIO);
  extend_path(path, trail + LOOKAHEAD);
  path.head = Math.min(trail, path.length);
  return path;
}

function advance_snake_path(path, delta) {
  path.pace_time -= delta;
  if (path.pace_time <= 0) {
    path.target_speed = MIN_SPEED + path.random() * SPEED_RANGE;
    path.pace_time = MIN_PACE_SECONDS + path.random() * PACE_RANGE_SECONDS;
  }
  path.speed += (path.target_speed - path.speed) * (1 - Math.exp(-SPEED_EASING * delta));
  path.head = Math.min(path.length, path.head + path.speed * delta);
  extend_path(path, path.head + LOOKAHEAD);
  let discard = 0;
  while (discard + 1 < path.points.length && path.points[discard + 1].distance < path.head - path.trail) {
    discard += 1;
  }
  if (discard > 0) {
    path.points.splice(0, discard);
  }
}

function snake_point(path, distance) {
  const offset = Math.max(path.points[0].distance, Math.min(path.length, distance));
  let low = 0;
  let high = path.points.length - 1;
  while (high - low > 1) {
    const middle = Math.floor((low + high) * HALF);
    if (path.points[middle].distance <= offset) {
      low = middle;
    } else {
      high = middle;
    }
  }
  const start = path.points[low];
  const end = path.points[high];
  let mix = 0;
  if (end.distance > start.distance) {
    mix = (offset - start.distance) / (end.distance - start.distance);
  }
  return {
    x: start.x + (end.x - start.x) * mix,
    y: start.y + (end.y - start.y) * mix,
    angle: Math.atan2(end.y - start.y, end.x - start.x) * DEGREES,
  };
}

export { snake_path, snake_point, advance_snake_path };
