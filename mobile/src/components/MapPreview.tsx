import React, { useState } from 'react';
import { View, StyleSheet, LayoutChangeEvent } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { RouteMap } from './RouteMap';
import { AppText } from './AppText';
import { colors, radius, spacing } from '../theme';
import type { GeoPoint } from '../api/types';

interface MapPreviewProps {
  origin: GeoPoint;
  destination: GeoPoint;
  waypoints?: GeoPoint[];
  originLabel: string;
  destinationLabel: string;
  height?: number;
}

/** Small rounded dark-map card with a route + origin/destination chips. */
export function MapPreview({
  origin,
  destination,
  waypoints,
  originLabel,
  destinationLabel,
  height = 150,
}: MapPreviewProps) {
  const [width, setWidth] = useState(0);

  const onLayout = (e: LayoutChangeEvent) =>
    setWidth(e.nativeEvent.layout.width);

  return (
    <View style={[styles.card, { height }]} onLayout={onLayout}>
      {width > 0 ? (
        <RouteMap
          origin={origin}
          destination={destination}
          waypoints={waypoints}
          width={width}
          height={height}
          compact
        />
      ) : null}

      {/* Floating origin → destination pill */}
      <View style={styles.overlay} pointerEvents="none">
        <View style={styles.pill}>
          <View style={styles.endpoint}>
            <View style={[styles.dot, { backgroundColor: colors.pickup }]} />
            <AppText variant="micro">{originLabel}</AppText>
          </View>
          <Ionicons name="arrow-back" size={13} color={colors.textSecondary} />
          <View style={styles.endpoint}>
            <View style={[styles.dot, { backgroundColor: colors.dropoff }]} />
            <AppText variant="micro">{destinationLabel}</AppText>
          </View>
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    borderRadius: radius.lg,
    overflow: 'hidden',
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.mapBase,
  },
  overlay: {
    ...StyleSheet.absoluteFillObject,
    alignItems: 'center',
    justifyContent: 'flex-start',
    paddingTop: spacing.md,
  },
  pill: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    backgroundColor: 'rgba(9,13,20,0.82)',
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.pill,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.xs,
  },
  endpoint: { flexDirection: 'row', alignItems: 'center', gap: spacing.xs },
  dot: { width: 7, height: 7, borderRadius: 4 },
});
