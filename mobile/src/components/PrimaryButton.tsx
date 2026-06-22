import React from 'react';
import {
  Pressable,
  StyleSheet,
  ActivityIndicator,
  View,
  ViewStyle,
  GestureResponderEvent,
} from 'react-native';
import * as Haptics from 'expo-haptics';
import { Ionicons } from '@expo/vector-icons';
import { AppText } from './AppText';
import { colors, radius, spacing } from '../theme';

export interface PrimaryButtonProps {
  label: string;
  onPress?: (e: GestureResponderEvent) => void;
  loading?: boolean;
  disabled?: boolean;
  /** 'primary' (blue) is default; 'success' renders the green accept CTA. */
  variant?: 'primary' | 'success';
  icon?: keyof typeof Ionicons.glyphMap;
  style?: ViewStyle;
}

/** Full-width solid CTA with press scale + haptic feedback. */
export function PrimaryButton({
  label,
  onPress,
  loading = false,
  disabled = false,
  variant = 'primary',
  icon,
  style,
}: PrimaryButtonProps) {
  const bg = variant === 'success' ? colors.success : colors.primary;
  const bgPressed =
    variant === 'success' ? colors.successPressed : colors.primaryPressed;
  const isDisabled = disabled || loading;

  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ disabled: isDisabled, busy: loading }}
      disabled={isDisabled}
      onPress={(e) => {
        Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium).catch(() => {});
        onPress?.(e);
      }}
      style={({ pressed }) => [
        styles.button,
        { backgroundColor: pressed ? bgPressed : bg },
        pressed && styles.pressed,
        isDisabled && styles.disabled,
        style,
      ]}
    >
      {loading ? (
        <ActivityIndicator color={colors.textOnPrimary} />
      ) : (
        <View style={styles.content}>
          {icon ? (
            <Ionicons name={icon} size={20} color={colors.textOnPrimary} />
          ) : null}
          <AppText variant="h3" tone="onPrimary" align="center">
            {label}
          </AppText>
        </View>
      )}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  button: {
    height: 56,
    borderRadius: radius.lg,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: spacing.lg,
  },
  content: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
  },
  pressed: { transform: [{ scale: 0.985 }] },
  disabled: { opacity: 0.45 },
});
