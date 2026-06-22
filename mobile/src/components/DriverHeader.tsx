import React from 'react';
import { View, StyleSheet, Pressable } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { AppText } from './AppText';
import { colors, radius, spacing } from '../theme';
import type { DriverProfile } from '../api/types';

interface DriverHeaderProps {
  driver: DriverProfile;
  /** Localized greeting prefix, e.g. "مساء الخير". */
  greeting?: string;
  notificationCount?: number;
  onPressNotifications?: () => void;
}

/** Dashboard header: avatar, greeting + plate, notification bell with badge. */
export function DriverHeader({
  driver,
  greeting = 'مساءً',
  notificationCount = 0,
  onPressNotifications,
}: DriverHeaderProps) {
  return (
    <View style={styles.row}>
      <View style={styles.identity}>
        <View style={styles.avatar}>
          <AppText variant="h3" tone="onPrimary">
            {driver.greetingName.charAt(0)}
          </AppText>
        </View>
        <View style={styles.texts}>
          <AppText variant="h2">
            {greeting} {driver.greetingName}
          </AppText>
          <View style={styles.plateRow}>
            <Ionicons name="cube-outline" size={14} color={colors.textSecondary} />
            <AppText variant="caption" tone="secondary">
              {driver.vehicleTypeLabel} • {driver.plateNumber}
            </AppText>
          </View>
        </View>
      </View>

      <Pressable
        accessibilityRole="button"
        accessibilityLabel="الإشعارات"
        onPress={onPressNotifications}
        style={({ pressed }) => [styles.bell, pressed && styles.pressed]}
      >
        <Ionicons name="notifications-outline" size={22} color={colors.textPrimary} />
        {notificationCount > 0 ? (
          <View style={styles.badge}>
            <AppText variant="micro" tone="onPrimary" align="center">
              {notificationCount}
            </AppText>
          </View>
        ) : null}
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  identity: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    flex: 1,
  },
  avatar: {
    width: 48,
    height: 48,
    borderRadius: radius.md,
    backgroundColor: colors.primary,
    alignItems: 'center',
    justifyContent: 'center',
  },
  texts: { gap: 2, flexShrink: 1 },
  plateRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.xs },
  bell: {
    width: 46,
    height: 46,
    borderRadius: radius.md,
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.border,
    alignItems: 'center',
    justifyContent: 'center',
  },
  pressed: { opacity: 0.7 },
  badge: {
    position: 'absolute',
    top: 8,
    // Logical edge: mirrors correctly under RTL/LTR (vs a hardcoded `left`).
    end: 8,
    minWidth: 16,
    height: 16,
    paddingHorizontal: 4,
    borderRadius: 8,
    backgroundColor: colors.danger,
    alignItems: 'center',
    justifyContent: 'center',
  },
});
