import React from 'react';
import { View, StyleSheet } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { LinearGradient } from 'expo-linear-gradient';
import { AppText } from './AppText';
import { PrimaryButton } from './PrimaryButton';
import { SecondaryButton } from './SecondaryButton';
import { colors, radius, spacing, shadow } from '../theme';
import type { ShipmentOrder } from '../api/types';
import {
  formatCurrency,
  formatDistanceKm,
  formatDuration,
  formatWeightTon,
  toArabicDigits,
} from '../utils/format';

interface OrderBottomSheetProps {
  order: ShipmentOrder;
  accepted: boolean;
  accepting?: boolean;
  onAccept: () => void;
  onIgnore: () => void;
  onStartNavigation?: () => void;
}

/** Floating glass summary sheet anchored to the bottom of the order map. */
export function OrderBottomSheet({
  order,
  accepted,
  accepting = false,
  onAccept,
  onIgnore,
  onStartNavigation,
}: OrderBottomSheetProps) {
  return (
    <View style={styles.sheet}>
      <View style={styles.handle} />

      {accepted ? (
        <View style={styles.acceptedBanner}>
          <Ionicons name="checkmark-circle" size={20} color={colors.success} />
          <AppText variant="h3" tone="success">
            تم قبول الطلب
          </AppText>
        </View>
      ) : null}

      {/* Headline metrics */}
      <View style={styles.metrics}>
        <Metric
          icon="navigate-outline"
          label="المسافة"
          value={formatDistanceKm(order.distanceKm)}
        />
        <View style={styles.metricDivider} />
        <Metric
          icon="time-outline"
          label="المدة"
          value={formatDuration(order.durationMinutes)}
        />
        <View style={styles.metricDivider} />
        <Metric
          icon="cash-outline"
          label="الأجرة المقترحة"
          value={formatCurrency(order.priceSar)}
          highlight
        />
      </View>

      {/* Requirements row */}
      <View style={styles.reqRow}>
        <Requirement
          icon="bus-outline"
          label="المطلوب"
          value={order.requiredVehicleLabel}
        />
        <Requirement
          icon="barbell-outline"
          label="الوزن"
          value={formatWeightTon(order.weightKg)}
        />
      </View>

      {/* Pickup → Dropoff timeline */}
      <View style={styles.timeline}>
        <Stop
          color={colors.pickup}
          title={order.pickupLabel}
          subtitle={order.pickupCity}
          line
        />
        <Stop
          color={colors.dropoff}
          title={order.dropoffLabel}
          subtitle={order.dropoffCity}
        />
      </View>

      {/* Company card */}
      <View style={styles.company}>
        <View style={styles.logo}>
          <Ionicons name="business" size={20} color={colors.primary} />
        </View>
        <View style={styles.companyTexts}>
          <AppText variant="h3">{order.company.name}</AppText>
          <View style={styles.companyMeta}>
            <Ionicons name="star" size={13} color={colors.warning} />
            <AppText variant="caption" tone="secondary">
              {toArabicDigits(order.company.rating.toFixed(1))}
            </AppText>
            <View style={styles.metaDot} />
            <AppText variant="caption" tone="secondary">
              {toArabicDigits(order.company.shipmentsCount)} شحنة
            </AppText>
          </View>
        </View>
        <View style={styles.verified}>
          <Ionicons name="shield-checkmark" size={16} color={colors.success} />
        </View>
      </View>

      {/* Actions */}
      {accepted ? (
        <PrimaryButton
          label="ابدأ الملاحة"
          variant="primary"
          icon="navigate"
          onPress={onStartNavigation}
        />
      ) : (
        <View style={styles.actions}>
          <PrimaryButton
            label="قبول الطلب"
            variant="success"
            icon="checkmark-circle-outline"
            loading={accepting}
            onPress={onAccept}
            style={styles.acceptBtn}
          />
          <SecondaryButton
            label="تجاهل"
            tone="danger"
            onPress={onIgnore}
            style={styles.ignoreBtn}
          />
        </View>
      )}
    </View>
  );
}

function Metric({
  icon,
  label,
  value,
  highlight,
}: {
  icon: keyof typeof Ionicons.glyphMap;
  label: string;
  value: string;
  highlight?: boolean;
}) {
  return (
    <View style={styles.metric}>
      <Ionicons
        name={icon}
        size={16}
        color={highlight ? colors.success : colors.textSecondary}
      />
      <AppText
        variant="h3"
        tone={highlight ? 'success' : 'primary'}
        align="center"
      >
        {value}
      </AppText>
      <AppText variant="micro" tone="muted" align="center">
        {label}
      </AppText>
    </View>
  );
}

function Requirement({
  icon,
  label,
  value,
}: {
  icon: keyof typeof Ionicons.glyphMap;
  label: string;
  value: string;
}) {
  return (
    <View style={styles.requirement}>
      <View style={styles.reqIcon}>
        <Ionicons name={icon} size={16} color={colors.primary} />
      </View>
      <View>
        <AppText variant="micro" tone="muted">
          {label}
        </AppText>
        <AppText variant="bodyStrong">{value}</AppText>
      </View>
    </View>
  );
}

function Stop({
  color,
  title,
  subtitle,
  line,
}: {
  color: string;
  title: string;
  subtitle: string;
  line?: boolean;
}) {
  return (
    <View style={styles.stopRow}>
      <View style={styles.stopMarker}>
        <View style={[styles.stopDot, { backgroundColor: color }]} />
        {line ? <View style={styles.stopLine} /> : null}
      </View>
      <View style={styles.stopTexts}>
        <AppText variant="bodyStrong">{title}</AppText>
        <AppText variant="caption" tone="secondary">
          {subtitle}
        </AppText>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  sheet: {
    backgroundColor: colors.backgroundElevated,
    borderTopLeftRadius: radius.xxl,
    borderTopRightRadius: radius.xxl,
    borderWidth: 1,
    borderColor: colors.borderStrong,
    paddingHorizontal: spacing.xl,
    paddingTop: spacing.md,
    paddingBottom: spacing.xl,
    gap: spacing.lg,
    ...shadow.floating,
  },
  handle: {
    alignSelf: 'center',
    width: 44,
    height: 5,
    borderRadius: 3,
    backgroundColor: colors.borderStrong,
    marginBottom: spacing.xs,
  },
  acceptedBanner: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.sm,
    backgroundColor: colors.successSoft,
    borderRadius: radius.md,
    paddingVertical: spacing.md,
  },
  metrics: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.card,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    paddingVertical: spacing.lg,
  },
  metric: { flex: 1, alignItems: 'center', gap: 4 },
  metricDivider: { width: 1, height: 36, backgroundColor: colors.border },
  reqRow: { flexDirection: 'row', gap: spacing.md },
  requirement: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    backgroundColor: colors.card,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.md,
  },
  reqIcon: {
    width: 34,
    height: 34,
    borderRadius: radius.sm,
    backgroundColor: colors.primarySoft,
    alignItems: 'center',
    justifyContent: 'center',
  },
  timeline: {
    backgroundColor: colors.card,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.lg,
  },
  stopRow: { flexDirection: 'row', gap: spacing.md },
  stopMarker: { alignItems: 'center', width: 14 },
  stopDot: { width: 12, height: 12, borderRadius: 6, marginTop: 4 },
  stopLine: { flex: 1, width: 2, backgroundColor: colors.border, marginVertical: 2 },
  stopTexts: { flex: 1, paddingBottom: spacing.md },
  company: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    backgroundColor: colors.card,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.md,
  },
  logo: {
    width: 44,
    height: 44,
    borderRadius: radius.md,
    backgroundColor: colors.primarySoft,
    alignItems: 'center',
    justifyContent: 'center',
  },
  companyTexts: { flex: 1, gap: 2 },
  companyMeta: { flexDirection: 'row', alignItems: 'center', gap: spacing.xs },
  metaDot: {
    width: 3,
    height: 3,
    borderRadius: 2,
    backgroundColor: colors.textMuted,
    marginHorizontal: spacing.xs,
  },
  verified: {
    width: 32,
    height: 32,
    borderRadius: radius.sm,
    backgroundColor: colors.successSoft,
    alignItems: 'center',
    justifyContent: 'center',
  },
  actions: { flexDirection: 'row', gap: spacing.md },
  // Ratio-based so both buttons scale on small screens instead of a fixed width.
  acceptBtn: { flex: 2 },
  ignoreBtn: { flex: 1 },
});
