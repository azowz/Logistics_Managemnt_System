import React from 'react';
import {
  Pressable,
  StyleSheet,
  View,
  ViewStyle,
  GestureResponderEvent,
} from 'react-native';
import * as Haptics from 'expo-haptics';
import { Ionicons } from '@expo/vector-icons';
import { AppText } from './AppText';
import { colors, radius, spacing } from '../theme';

export interface SecondaryButtonProps {
  label: string;
  onPress?: (e: GestureResponderEvent) => void;
  disabled?: boolean;
  /** 'outline' (default) or 'ghost' (no border, transparent). */
  variant?: 'outline' | 'ghost';
  icon?: keyof typeof Ionicons.glyphMap;
  tone?: 'neutral' | 'danger';
  style?: ViewStyle;
}

/** Bordered/ghost secondary action — pairs with PrimaryButton. */
export function SecondaryButton({
  label,
  onPress,
  disabled = false,
  variant = 'outline',
  icon,
  tone = 'neutral',
  style,
}: SecondaryButtonProps) {
  const textTone = tone === 'danger' ? 'danger' : 'primary';
  const iconColor = tone === 'danger' ? colors.danger : colors.textPrimary;

  return (
    <Pressable
      accessibilityRole="button"
      disabled={disabled}
      onPress={(e) => {
        Haptics.selectionAsync().catch(() => {});
        onPress?.(e);
      }}
      style={({ pressed }) => [
        styles.button,
        variant === 'outline' && styles.outline,
        pressed && styles.pressed,
        disabled && styles.disabled,
        style,
      ]}
    >
      <View style={styles.content}>
        {icon ? <Ionicons name={icon} size={19} color={iconColor} /> : null}
        <AppText variant="bodyStrong" tone={textTone} align="center">
          {label}
        </AppText>
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  button: {
    height: 54,
    borderRadius: radius.lg,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: spacing.lg,
    backgroundColor: colors.cardElevated,
  },
  outline: {
    backgroundColor: 'transparent',
    borderWidth: 1,
    borderColor: colors.borderStrong,
  },
  content: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
  },
  pressed: { opacity: 0.7, transform: [{ scale: 0.985 }] },
  disabled: { opacity: 0.4 },
});
