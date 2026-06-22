import React, { useEffect, useRef } from 'react';
import { View, StyleSheet, Animated, Easing } from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import { AppText } from './AppText';
import { Toggle } from './Toggle';
import { colors, radius, spacing } from '../theme';

interface StatusCardProps {
  isOnline: boolean;
  onToggle: (value: boolean) => void;
}

/**
 * Online/offline hero card. When online it shows a pulsing green indicator and
 * a "searching for nearby shipments" subtitle; offline collapses to neutral.
 */
export function StatusCard({ isOnline, onToggle }: StatusCardProps) {
  const pulse = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    if (!isOnline) {
      pulse.stopAnimation();
      pulse.setValue(0);
      return;
    }
    const loop = Animated.loop(
      Animated.sequence([
        Animated.timing(pulse, {
          toValue: 1,
          duration: 1400,
          easing: Easing.out(Easing.ease),
          useNativeDriver: true,
        }),
        Animated.timing(pulse, {
          toValue: 0,
          duration: 0,
          useNativeDriver: true,
        }),
      ]),
    );
    loop.start();
    return () => loop.stop();
  }, [isOnline, pulse]);

  const ringScale = pulse.interpolate({ inputRange: [0, 1], outputRange: [1, 2.6] });
  const ringOpacity = pulse.interpolate({ inputRange: [0, 1], outputRange: [0.5, 0] });

  return (
    <LinearGradient
      colors={
        isOnline
          ? ['rgba(24,197,110,0.18)', 'rgba(24,197,110,0.04)']
          : [colors.card, colors.card]
      }
      start={{ x: 0, y: 0 }}
      end={{ x: 1, y: 1 }}
      style={[styles.card, { borderColor: isOnline ? colors.successSoft : colors.border }]}
    >
      <View style={styles.row}>
        <View style={styles.indicatorWrap}>
          {isOnline ? (
            <Animated.View
              style={[
                styles.ring,
                { transform: [{ scale: ringScale }], opacity: ringOpacity },
              ]}
            />
          ) : null}
          <View
            style={[
              styles.dot,
              { backgroundColor: isOnline ? colors.success : colors.textMuted },
            ]}
          />
        </View>

        <View style={styles.texts}>
          <AppText variant="h3" tone={isOnline ? 'success' : 'secondary'}>
            {isOnline ? 'أنت متصل الآن' : 'أنت غير متصل'}
          </AppText>
          <AppText variant="caption" tone="secondary">
            {isOnline
              ? 'جاري البحث عن طلبات شحن قريبة...'
              : 'فعّل الاتصال لاستقبال طلبات الشحن'}
          </AppText>
        </View>

        <Toggle value={isOnline} onValueChange={onToggle} />
      </View>
    </LinearGradient>
  );
}

const styles = StyleSheet.create({
  card: {
    borderRadius: radius.xl,
    borderWidth: 1,
    padding: spacing.lg,
  },
  row: { flexDirection: 'row', alignItems: 'center', gap: spacing.md },
  indicatorWrap: {
    width: 18,
    height: 18,
    alignItems: 'center',
    justifyContent: 'center',
  },
  ring: {
    position: 'absolute',
    width: 14,
    height: 14,
    borderRadius: 7,
    backgroundColor: colors.success,
  },
  dot: { width: 12, height: 12, borderRadius: 6 },
  texts: { flex: 1, gap: 2 },
});
