import React from 'react';
import { View, StyleSheet } from 'react-native';
import Svg, { Circle } from 'react-native-svg';
import { AppText } from './AppText';
import { colors } from '../theme';
import { toArabicDigits } from '../utils/format';

interface CountdownBadgeProps {
  /** Remaining seconds (controlled — pair with useCountdown). */
  remaining: number;
  total: number;
  size?: number;
}

/**
 * Circular countdown ring. The arc depletes as time runs out and shifts
 * blue → orange → red in the final seconds.
 */
export function CountdownBadge({
  remaining,
  total,
  size = 64,
}: CountdownBadgeProps) {
  const stroke = 5;
  const r = (size - stroke) / 2;
  const circumference = 2 * Math.PI * r;
  const progress = Math.max(0, Math.min(1, remaining / total));

  const color =
    remaining <= 5 ? colors.danger : remaining <= 10 ? colors.warning : colors.primary;

  return (
    <View style={[styles.wrap, { width: size, height: size }]}>
      <Svg width={size} height={size}>
        {/* Track */}
        <Circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          stroke={colors.border}
          strokeWidth={stroke}
          fill={colors.card}
        />
        {/* Progress arc — starts at 12 o'clock */}
        <Circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          stroke={color}
          strokeWidth={stroke}
          fill="none"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={circumference * (1 - progress)}
          rotation={-90}
          origin={`${size / 2}, ${size / 2}`}
        />
      </Svg>
      <View style={styles.center} pointerEvents="none">
        <AppText variant="h3" style={{ color }} align="center">
          {toArabicDigits(remaining)}
        </AppText>
        <AppText variant="micro" tone="muted" align="center">
          ثانية
        </AppText>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { alignItems: 'center', justifyContent: 'center' },
  center: { ...StyleSheet.absoluteFillObject, alignItems: 'center', justifyContent: 'center' },
});
