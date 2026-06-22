import type { GeoPoint } from '../api/types';

export interface Point {
  x: number;
  y: number;
}

/**
 * Projects a set of geo points into a width×height box with padding, preserving
 * relative shape (simple equirectangular fit — good enough for stylized route
 * previews, not navigation). Returns projected pixel points.
 */
export function projectPoints(
  geo: GeoPoint[],
  width: number,
  height: number,
  padding = 28,
): Point[] {
  if (geo.length === 0) return [];

  const lats = geo.map((g) => g.lat);
  const lngs = geo.map((g) => g.lng);
  const minLat = Math.min(...lats);
  const maxLat = Math.max(...lats);
  const minLng = Math.min(...lngs);
  const maxLng = Math.max(...lngs);

  const spanLat = maxLat - minLat || 1;
  const spanLng = maxLng - minLng || 1;
  const innerW = width - padding * 2;
  const innerH = height - padding * 2;

  return geo.map((g) => ({
    // lng → x (west-left); lat → y (north-up, so invert).
    x: padding + ((g.lng - minLng) / spanLng) * innerW,
    y: padding + (1 - (g.lat - minLat) / spanLat) * innerH,
  }));
}

/** Smooth cubic-bezier SVG path through the given points (Catmull-Rom-ish). */
export function smoothPath(points: Point[]): string {
  if (points.length === 0) return '';
  if (points.length === 1) return `M ${points[0].x} ${points[0].y}`;

  let d = `M ${points[0].x} ${points[0].y}`;
  for (let i = 0; i < points.length - 1; i++) {
    const p0 = points[i === 0 ? 0 : i - 1];
    const p1 = points[i];
    const p2 = points[i + 1];
    const p3 = points[i + 2 < points.length ? i + 2 : i + 1];

    const cp1x = p1.x + (p2.x - p0.x) / 6;
    const cp1y = p1.y + (p2.y - p0.y) / 6;
    const cp2x = p2.x - (p3.x - p1.x) / 6;
    const cp2y = p2.y - (p3.y - p1.y) / 6;

    d += ` C ${cp1x} ${cp1y}, ${cp2x} ${cp2y}, ${p2.x} ${p2.y}`;
  }
  return d;
}
