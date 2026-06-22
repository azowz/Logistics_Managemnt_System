import React from 'react';
import { View, StyleSheet } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { AppText } from './AppText';
import { colors, radius, spacing } from '../theme';

export interface KPIBoxProps {
  label: string;
  value: string;
  unit?: string;
  icon: keyof typeof Ionicons.glyphMap;
  /** Accent color for the icon chip. */
  tint?: string;
}

/** Compact metric tile used in the dashboard KPI grid. */
export function KPIBox({
  label,
  value,
  unit,
  icon,
  tint = colors.primary,
}: KPIBoxProps) {
  return (
    <View style={styles.box}>
      <View style={[styles.iconChip, { backgroundColor: `${tint}22` }]}>
        <Ionicons name={icon} size={18} color={tint} />
      </View>
      <View style={styles.valueRow}>
        <AppText variant="numeric">{value}</AppText>
        {unit ? (
          <AppText variant="caption" tone="secondary" style={styles.unit}>
            {unit}
          </AppText>
        ) : null}
      </View>
      <AppText variant="caption" tone="secondary">
        {label}
      </AppText>
    </View>
  );
}

const styles = StyleSheet.create({
  box: {
    flex: 1,
    minWidth: '47%',
    backgroundColor: colors.card,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.lg,
    gap: spacing.sm,
  },
  iconChip: {
    width: 36,
    height: 36,
    borderRadius: radius.sm,
    alignItems: 'center',
    justifyContent: 'center',
  },
  valueRow: { flexDirection: 'row', alignItems: 'baseline', gap: spacing.xs },
  unit: { marginBottom: 2 },
});
