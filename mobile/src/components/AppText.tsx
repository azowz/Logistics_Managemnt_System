import React from 'react';
import { Text, TextProps, StyleSheet, TextStyle } from 'react-native';
import { colors, typography } from '../theme';

type Variant = keyof typeof typography;
type Tone = 'primary' | 'secondary' | 'muted' | 'brand' | 'success' | 'danger' | 'onPrimary';

const toneColor: Record<Tone, string> = {
  primary: colors.textPrimary,
  secondary: colors.textSecondary,
  muted: colors.textMuted,
  brand: colors.primary,
  success: colors.success,
  danger: colors.danger,
  onPrimary: colors.textOnPrimary,
};

interface AppTextProps extends TextProps {
  variant?: Variant;
  tone?: Tone;
  align?: TextStyle['textAlign'];
}

/** Typed Text wrapper that applies the design-system scale + RTL-aware align. */
export function AppText({
  variant = 'body',
  tone = 'primary',
  align = 'right',
  style,
  ...rest
}: AppTextProps) {
  return (
    <Text
      style={[
        typography[variant] as TextStyle,
        { color: toneColor[tone], textAlign: align, writingDirection: 'rtl' },
        style,
      ]}
      {...rest}
    />
  );
}

export const textStyles = StyleSheet.create({});
