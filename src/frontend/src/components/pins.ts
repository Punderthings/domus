// Geometry for pins on an image. Positions are stored as 0-1 fractions of the
// image's width and height, so they survive replacing the image with another
// resolution; the screen only ever sees pixels.

export interface Size {
  width: number;
  height: number;
}

export interface Point {
  x: number;
  y: number;
}

export function clamp01(value: number): number {
  if (!Number.isFinite(value)) return 0;
  return Math.min(1, Math.max(0, value));
}

/** Scale an image to `maxWidth`, keeping its aspect ratio; never scales up. */
export function fitToWidth(image: Size, maxWidth: number): Size {
  if (image.width <= 0 || image.height <= 0 || maxWidth <= 0) return { width: 0, height: 0 };
  const scale = Math.min(1, maxWidth / image.width);
  return { width: Math.round(image.width * scale), height: Math.round(image.height * scale) };
}

/** Pixels on the drawn image to a stored 0-1 position. */
export function toNormalized(point: Point, drawn: Size): Point {
  if (drawn.width <= 0 || drawn.height <= 0) return { x: 0, y: 0 };
  return { x: clamp01(point.x / drawn.width), y: clamp01(point.y / drawn.height) };
}

/** A stored 0-1 position to pixels on the drawn image. */
export function toPixels(point: Point, drawn: Size): Point {
  return { x: clamp01(point.x) * drawn.width, y: clamp01(point.y) * drawn.height };
}

/** Round to 4 decimals (0.1 mm on a 1 m image) so saved positions stay short. */
export function roundPosition(point: Point): Point {
  return { x: Math.round(point.x * 10_000) / 10_000, y: Math.round(point.y * 10_000) / 10_000 };
}
