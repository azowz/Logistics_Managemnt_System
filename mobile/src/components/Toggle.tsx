import React, { useEffect, useRef } from 'react';
import { Pressable, Animated, StyleSheet, I18nManager } from 'react-native';
import * as Haptics from 'expo-haptics';
import { colors } from '../theme';

interface ToggleProps {
  value: boolean;
  onValueChange: (value: boolean) => void;
  activeColor?: string;
}

const TRACK_W = 52;
const TRACK_H = 30;
const KNOB = 24;
const PAD = 3;

/** Custom animated switch — RTL-aware knob travel, haptic on change. */
export function Toggle({
  value,
  onValueChange,
  activeColor = colors.success,
}: ToggleProps) {
  const anim = useRef(new Animated.Value(value ? 1 : 0)).current;

  useEffect(() => {
    Animated.spring(anim, {
      toValue: value ? 1 : 0,
      useNativeDriver: false,
      bounciness: 6,
      speed: 14,
    }).start();
  }, [value, anim]);

  const travel = TRACK_W - KNOB - PAD * 2;
  // In RTL the "on" knob rests on the left.
  const translateX = anim.interpolate({
    inputRange: [0, 1],
    outputRange: I18nManager.isRTL ? [travel, 0] : [0, travel],
  });
  const backgroundColor = anim.interpolate({
    inputRange: [0, 1],
    outputRange: [colors.cardElevated, activeColor],
  });

  return (
    <Pressable
      accessibilityRole="switch"
      accessibilityState={{ checked: value }}
      onPress={() => {
        Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light).catch(() => {});
        onValueChange(!value);
      }}
      hitSlop={8}
    >
      <Animated.View style={[styles.track, { backgroundColor }]}>
        <Animated.View style={[styles.knob, { transform: [{ translateX }] }]} />
      </Animated.View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  track: {
    width: TRACK_W,
    height: TRACK_H,
    borderRadius: TRACK_H / 2,
    padding: PAD,
    justifyContent: 'center',
    borderWidth: 1,
    borderColor: colors.border,
  },
  knob: {
    width: KNOB,
    height: KNOB,
    borderRadius: KNOB / 2,
    backgroundColor: '#FFFFFF',
  },
});
