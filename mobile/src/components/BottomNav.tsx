import React from 'react';
import { View, Pressable, StyleSheet, Platform } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import * as Haptics from 'expo-haptics';
import { Ionicons } from '@expo/vector-icons';
import { AppText } from './AppText';
import { colors, radius, spacing } from '../theme';

export type TabKey = 'home' | 'orders' | 'navigation' | 'messages' | 'performance';

interface TabDef {
  key: TabKey;
  label: string;
  icon: keyof typeof Ionicons.glyphMap;
  activeIcon: keyof typeof Ionicons.glyphMap;
  badge?: number;
}

const TABS: TabDef[] = [
  { key: 'home', label: 'الرئيسية', icon: 'home-outline', activeIcon: 'home' },
  { key: 'orders', label: 'الطلبات', icon: 'cube-outline', activeIcon: 'cube' },
  { key: 'navigation', label: 'الملاحة', icon: 'navigate-outline', activeIcon: 'navigate' },
  { key: 'messages', label: 'الرسائل', icon: 'chatbubble-outline', activeIcon: 'chatbubble', badge: 2 },
  { key: 'performance', label: 'الأداء', icon: 'stats-chart-outline', activeIcon: 'stats-chart' },
];

interface BottomNavProps {
  active: TabKey;
  onChange?: (key: TabKey) => void;
}

/** Fixed bottom tab bar with an active blue pill state. */
export function BottomNav({ active, onChange }: BottomNavProps) {
  const insets = useSafeAreaInsets();

  return (
    <View style={[styles.bar, { paddingBottom: Math.max(insets.bottom, spacing.md) }]}>
      {TABS.map((tab) => {
        const isActive = tab.key === active;
        return (
          <Pressable
            key={tab.key}
            accessibilityRole="tab"
            accessibilityState={{ selected: isActive }}
            accessibilityLabel={tab.label}
            onPress={() => {
              Haptics.selectionAsync().catch(() => {});
              onChange?.(tab.key);
            }}
            style={styles.tab}
          >
            <View style={[styles.iconWrap, isActive && styles.iconWrapActive]}>
              <Ionicons
                name={isActive ? tab.activeIcon : tab.icon}
                size={22}
                color={isActive ? colors.primary : colors.textMuted}
              />
              {tab.badge ? (
                <View style={styles.badge}>
                  <AppText variant="micro" tone="onPrimary">
                    {tab.badge}
                  </AppText>
                </View>
              ) : null}
            </View>
            <AppText
              variant="micro"
              tone={isActive ? 'brand' : 'muted'}
              align="center"
            >
              {tab.label}
            </AppText>
          </Pressable>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  bar: {
    flexDirection: 'row',
    backgroundColor: colors.backgroundElevated,
    borderTopWidth: 1,
    borderTopColor: colors.border,
    paddingTop: spacing.md,
    paddingHorizontal: spacing.sm,
    ...Platform.select({
      ios: { shadowColor: '#000', shadowOpacity: 0.4, shadowRadius: 16, shadowOffset: { width: 0, height: -4 } },
      android: { elevation: 16 },
    }),
  },
  tab: { flex: 1, alignItems: 'center', gap: 4 },
  iconWrap: {
    width: 52,
    height: 34,
    borderRadius: radius.pill,
    alignItems: 'center',
    justifyContent: 'center',
  },
  iconWrapActive: { backgroundColor: colors.primarySoft },
  badge: {
    position: 'absolute',
    top: 2,
    // Logical edge: mirrors correctly under RTL/LTR (vs a hardcoded `left`).
    end: 10,
    minWidth: 15,
    height: 15,
    paddingHorizontal: 3,
    borderRadius: 8,
    backgroundColor: colors.danger,
    alignItems: 'center',
    justifyContent: 'center',
  },
});
