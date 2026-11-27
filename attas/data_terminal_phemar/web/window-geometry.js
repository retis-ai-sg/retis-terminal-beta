/** Pure canvas-relative window geometry. Coordinates and sizes use CSS pixels. */

const finite = (value, fallback) => typeof value === 'number' && Number.isFinite(value) ? value : fallback;
const clamp = (value, minimum, maximum) => Math.min(Math.max(value, minimum), maximum);

function canvasBounds(bounds) {
  return {
    width: Math.max(1, finite(bounds?.width, 1024)),
    height: Math.max(1, finite(bounds?.height, 768)),
  };
}

/** Sanitize saved geometry and keep the complete frame inside the canvas. */
export function normalizeFrame(frame, bounds) {
  const canvas = canvasBounds(bounds);
  const width = clamp(finite(frame?.width, 620), Math.min(360, canvas.width), canvas.width);
  const height = clamp(finite(frame?.height, 560), Math.min(280, canvas.height), canvas.height);
  return {
    x: clamp(finite(frame?.x, 0), 0, canvas.width - width),
    y: clamp(finite(frame?.y, 0), 0, canvas.height - height),
    width,
    height,
  };
}

/** Move an existing frame by a pointer delta without changing its dimensions. */
export function moveFrame(frame, dx, dy, bounds) {
  const base = normalizeFrame(frame, bounds);
  return normalizeFrame({
    ...base,
    x: base.x + finite(dx, 0),
    y: base.y + finite(dy, 0),
  }, bounds);
}

/** Resize an edge or corner while anchoring its opposite edge(s). */
export function resizeFrame(frame, edge, dx, dy, bounds) {
  const canvas = canvasBounds(bounds);
  const base = normalizeFrame(frame, canvas);
  if (!['n', 's', 'e', 'w', 'ne', 'nw', 'se', 'sw'].includes(edge)) return base;

  const minWidth = Math.min(360, canvas.width);
  const minHeight = Math.min(280, canvas.height);
  const deltaX = finite(dx, 0);
  const deltaY = finite(dy, 0);
  let left = base.x;
  let top = base.y;
  let right = base.x + base.width;
  let bottom = base.y + base.height;

  if (edge.includes('w')) left = clamp(left + deltaX, 0, right - minWidth);
  if (edge.includes('e')) right = clamp(right + deltaX, left + minWidth, canvas.width);
  if (edge.includes('n')) top = clamp(top + deltaY, 0, bottom - minHeight);
  if (edge.includes('s')) bottom = clamp(bottom + deltaY, top + minHeight, canvas.height);

  return { x: left, y: top, width: right - left, height: bottom - top };
}

/**
 * Tile row-major with 12px gaps, in columns about 500px wide. When those rows would not fit at the minimum height,
 * use more columns (down to the minimum width) until they do, so no window covers another's title bar: five windows
 * on a 1400 x 700 canvas tile 3 x 2, not 2 x 3. Only when no column count fits do the rows overlap evenly, as before,
 * while remaining fully in bounds. A host can grow its scrollable canvas to avoid that compact fallback.
 */
export function tileFrames(count, bounds) {
  const total = Math.max(0, Math.floor(finite(count, 0)));
  if (total === 0) return [];
  const canvas = canvasBounds(bounds);
  const gap = 12;
  const minWidth = Math.min(360, canvas.width);
  const minHeight = Math.min(280, canvas.height);
  const preferred = Math.max(1, Math.min(total, Math.floor(canvas.width / 500)));
  const fits = columns => (canvas.width - gap * (columns - 1)) / columns >= minWidth
    && Math.ceil(total / columns) * (minHeight + gap) - gap <= canvas.height;
  let columns = preferred;
  for (let more = preferred; more <= total; more += 1) if (fits(more)) { columns = more; break; }
  const rows = Math.ceil(total / columns);
  const width = Math.max(minWidth, (canvas.width - gap * (columns - 1)) / columns);
  const height = Math.max(minHeight, (canvas.height - gap * (rows - 1)) / rows);
  const rowStep = rows > 1 ? Math.min(height + gap, (canvas.height - height) / (rows - 1)) : 0;

  return Array.from({ length: total }, (_, index) => normalizeFrame({
    x: (index % columns) * (width + gap),
    y: Math.floor(index / columns) * rowStep,
    width,
    height,
  }, canvas));
}

/**
 * Where a newly opened window goes beside the open ones: the first tile of an even arrangement for one more
 * window that no open window covers by more than a fifth, or null when every tile is taken.
 */
export function freeFrame(frames, bounds) {
  const open = (frames || []).filter(Boolean);
  const area = (a, b) => Math.max(0, Math.min(a.x + a.width, b.x + b.width) - Math.max(a.x, b.x))
    * Math.max(0, Math.min(a.y + a.height, b.y + b.height) - Math.max(a.y, b.y));
  return tileFrames(open.length + 1, bounds).find(tile => open.every(frame => area(tile, frame) <= tile.width * tile.height / 5)) || null;
}

/** Place a newly opened window 28px beyond its predecessor, bounded to canvas. */
export function cascadeFrame(index, bounds) {
  const canvas = canvasBounds(bounds);
  const offset = Math.max(0, Math.floor(finite(index, 0))) * 28;
  return normalizeFrame({
    x: offset,
    y: offset,
    width: Math.min(620, canvas.width),
    height: Math.min(560, canvas.height),
  }, canvas);
}

/**
 * Where a newly opened window goes without moving any open one: a free tile (freeFrame), else the first cascade
 * step that does not start where an open window starts, so it never hides another's title bar exactly. The open
 * windows stay where they are; only the person's Tile or Arrange windows tiles them again.
 */
export function openingFrame(frames, bounds) {
  const free = freeFrame(frames, bounds);
  if (free) return free;
  const open = (frames || []).filter(Boolean);
  const taken = frame => open.some(other => Math.abs(other.x - frame.x) < 8 && Math.abs(other.y - frame.y) < 8);
  for (let step = 0; step <= open.length; step += 1) {
    const frame = cascadeFrame(step, bounds);
    if (!taken(frame)) return frame;
  }
  return cascadeFrame(open.length, bounds);
}
