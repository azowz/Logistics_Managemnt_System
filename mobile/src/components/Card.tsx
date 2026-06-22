import React from 'react';
import { View, StyleSheet, ViewStyle } from 'react-native';
import { colors, radius, spacing, shadow } from '../theme';

interface CardProps {
  children: React.ReactNode;
  style?: ViewStyle;
  elevated?: boolean;
  padded?: boolean;
}

/** Base rounded surface used by most cards in the app. */
export function Card({
  children,
  style,
  elevated = false,
  padded = true,
}: CardProps) {
  return (
    <View
      style={[
        styles.card,
        elevated && styles.elevated,
        padded && styles.padded,
        style,
      ]}
    >
      {children}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.card,
    borderRadius: radius.xl,
    borderWidth: 1,
    borderColor: colors.border,
  },
  elevated: {
    backgroundColor: colors.cardElevated,
    ...shadow.card,
  },
  padded: { padding: spacing.lg },
});
