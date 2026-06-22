import React, { useMemo } from 'react';
import { StyleSheet, View } from 'react-native';
import Svg, {
  Defs,
  LinearGradient as SvgGradient,
  Stop,
  Rect,
  Line,
  Path,
  Circle,
  G,
} from 'react-native-svg';
import { colors } from '../theme';
import type { GeoPoint } from '../api/types';
import { projectPoints, smoothPath } from '../utils/mapProjection';

interface RouteMapProps {
  origin: GeoPoint;
  destination: GeoPoint;
  waypoints?: GeoPoint[];
  width: number;
  height: number;
  /** Smaller markers/grid for the dashboard preview. */
  compact?: boolean;
}

/**
 * Stylized dark map with a glowing route line and pickup/dropoff markers,
 * rendered entirely in SVG (no native map dependency). Used full-screen on the
 * order screen and compact on the dashboard.
 */
export function RouteMap({
  origin,
  destination,
  waypoints = [],
  width,
  height,
  compact = false,
}: RouteMapProps) {
  const { path, points } = useMemo(() => {
    const geo = [origin, ...waypoints, destination];
    const projected = projectPoints(geo, width, height, compact ? 22 : 48);
    return { path: smoothPath(projected), points: projected };
  }, [origin, destination, waypoints, width, height, compact]);

  const start = points[0];
  const end = points[points.length - 1];
  const gridStep = compact ? 34 : 56;
  const cols = Math.ceil(width / gridStep);
  const rows = Math.ceil(height / gridStep);

  return (
    <View style={styles.wrap}>
      <Svg width={width} height={height}>
        <Defs>
          <SvgGradient id="routeGrad" x1="0" y1="0" x2="1" y2="1">
            <Stop offset="0" stopColor={colors.success} />
            <Stop offset="1" stopColor={colors.primary} />
          </SvgGradient>
          <SvgGradient id="mapFade" x1="0" y1="0" x2="0" y2="1">
            <Stop offset="0" stopColor="#0B1018" />
            <Stop offset="1" stopColor={colors.mapBase} />
          </SvgGradient>
        </Defs>

        {/* Base canvas */}
        <Rect x={0} y={0} width={width} height={height} fill="url(#mapFade)" />

        {/* Map grid */}
        <G>
          {Array.from({ length: cols + 1 }).map((_, i) => (
            <Line
              key={`v${i}`}
              x1={i * gridStep}
              y1={0}
              x2={i * gridStep}
              y2={height}
              stroke={colors.mapGrid}
              strokeWidth={1}
            />
          ))}
          {Array.from({ length: rows + 1 }).map((_, i) => (
            <Line
              key={`h${i}`}
              x1={0}
              y1={i * gridStep}
              x2={width}
              y2={i * gridStep}
              stroke={colors.mapGrid}
              strokeWidth={1}
            />
          ))}
        </G>

        {/* Faux roads for depth */}
        <Line
          x1={width * 0.12}
          y1={height}
          x2={width * 0.7}
          y2={0}
          stroke={colors.mapRoad}
          strokeWidth={compact ? 6 : 12}
          strokeLinecap="round"
        />
        <Line
          x1={0}
          y1={height * 0.32}
          x2={width}
          y2={height * 0.55}
          stroke={colors.mapRoad}
          strokeWidth={compact ? 5 : 10}
          strokeLinecap="round"
        />

        {/* Route glow + line */}
        <Path
          d={path}
          stroke={colors.routeGlow}
          strokeWidth={compact ? 10 : 16}
          fill="none"
          strokeLinecap="round"
        />
        <Path
          d={path}
          stroke="url(#routeGrad)"
          strokeWidth={compact ? 3.5 : 5}
          fill="none"
          strokeLinecap="round"
          strokeDasharray={compact ? undefined : '1 0'}
        />

        {/* Pickup marker */}
        {start ? (
          <G>
            <Circle cx={start.x} cy={start.y} r={compact ? 10 : 16} fill={colors.successSoft} />
            <Circle cx={start.x} cy={start.y} r={compact ? 5 : 8} fill={colors.success} />
            <Circle cx={start.x} cy={start.y} r={compact ? 2 : 3} fill="#fff" />
          </G>
        ) : null}

        {/* Dropoff marker */}
        {end ? (
          <G>
            <Circle cx={end.x} cy={end.y} r={compact ? 10 : 16} fill={colors.dangerSoft} />
            <Circle cx={end.x} cy={end.y} r={compact ? 5 : 8} fill={colors.dropoff} />
            <Circle cx={end.x} cy={end.y} r={compact ? 2 : 3} fill="#fff" />
          </G>
        ) : null}
      </Svg>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { overflow: 'hidden', backgroundColor: colors.mapBase },
});
