import React from 'react';
import { Pressable, View, StyleSheet } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { AppText } from './AppText';
import { colors, radius, spacing } from '../theme';
import type { ShipmentRequest } from '../api/types';
import {
  formatCurrency,
  formatDistanceKm,
  formatWeightTon,
  toArabicDigits,
} from '../utils/format';

interface ShipmentRequestCardProps {
  request: ShipmentRequest;
  onPress?: (request: ShipmentRequest) => void;
}

/** Tappable offer row: route, cargo, distance/weight chips and the fare. */
export function ShipmentRequestCard({
  request,
  onPress,
}: ShipmentRequestCardProps) {
  return (
    <Pressable
      accessibilityRole="button"
      onPress={() => onPress?.(request)}
      style={({ pressed }) => [styles.card, pressed && styles.pressed]}
    >
      {/* Top: route + badge */}
      <View style={styles.header}>
        <View style={styles.route}>
          <View style={[styles.dot, { backgroundColor: colors.pickup }]} />
          <AppText variant="h3">{request.originCity}</AppText>
          <Ionicons name="arrow-back" size={16} color={colors.textSecondary} />
          <View style={[styles.dot, { backgroundColor: colors.dropoff }]} />
          <AppText variant="h3">{request.destinationCity}</AppText>
        </View>
        {request.badge ? (
          <View style={styles.badge}>
            <AppText variant="micro" tone="onPrimary">
              {request.badge}
            </AppText>
          </View>
        ) : null}
      </View>

      {/* Cargo type */}
      <View style={styles.cargoRow}>
        <Ionicons name="cube-outline" size={15} color={colors.textSecondary} />
        <AppText variant="caption" tone="secondary">
          {request.cargoType} • {request.requiredVehicleLabel}
        </AppText>
      </View>

      {/* Chips + price */}
      <View style={styles.footer}>
        <View style={styles.chips}>
          <Chip icon="navigate-outline" text={formatDistanceKm(request.distanceKm)} />
          <Chip icon="barbell-outline" text={formatWeightTon(request.weightKg)} />
          <Chip
            icon="time-outline"
            text={`قبل ${toArabicDigits(request.postedMinutesAgo)} د`}
          />
        </View>
        <View style={styles.priceWrap}>
          <AppText variant="micro" tone="secondary">
            السعر
          </AppText>
          <AppText variant="h3" tone="success">
            {formatCurrency(request.priceSar)}
          </AppText>
        </View>
      </View>
    </Pressable>
  );
}

function Chip({
  icon,
  text,
}: {
  icon: keyof typeof Ionicons.glyphMap;
  text: string;
}) {
  return (
    <View style={styles.chip}>
      <Ionicons name={icon} size={13} color={colors.textSecondary} />
      <AppText variant="micro" tone="secondary">
        {text}
      </AppText>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.card,
    borderRadius: radius.xl,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.lg,
    gap: spacing.md,
  },
  pressed: { backgroundColor: colors.cardElevated, transform: [{ scale: 0.99 }] },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  route: { flexDirection: 'row', alignItems: 'center', gap: spacing.xs, flexShrink: 1 },
  dot: { width: 8, height: 8, borderRadius: 4 },
  badge: {
    backgroundColor: colors.warning,
    borderRadius: radius.pill,
    paddingHorizontal: spacing.sm,
    paddingVertical: 3,
  },
  cargoRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.xs },
  footer: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    justifyContent: 'space-between',
    gap: spacing.md,
  },
  chips: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, flexWrap: 'wrap', flex: 1 },
  chip: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
    backgroundColor: colors.cardMuted,
    borderRadius: radius.sm,
    paddingHorizontal: spacing.sm,
    paddingVertical: 5,
  },
  priceWrap: { alignItems: 'flex-end' },
});
