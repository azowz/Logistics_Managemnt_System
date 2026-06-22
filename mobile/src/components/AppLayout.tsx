import React from 'react';
import {
  View,
  StyleSheet,
  StatusBar,
  ViewStyle,
  ScrollView,
} from 'react-native';
import { SafeAreaView, Edge } from 'react-native-safe-area-context';
import { LinearGradient } from 'expo-linear-gradient';
import { colors, theme } from '../theme';

interface AppLayoutProps {
  children: React.ReactNode;
  /** Wrap content in a ScrollView (default for long screens). */
  scroll?: boolean;
  /** Remove default horizontal gutter (e.g. full-bleed map screens). */
  bleed?: boolean;
  edges?: readonly Edge[];
  contentStyle?: ViewStyle;
  contentContainerStyle?: ViewStyle;
}

/**
 * Root screen shell: dark canvas, ambient top glow, safe-area handling and an
 * optional scroll container. Every screen renders inside this.
 */
export function AppLayout({
  children,
  scroll = false,
  bleed = false,
  edges = ['top', 'bottom'],
  contentStyle,
  contentContainerStyle,
}: AppLayoutProps) {
  const padding = bleed ? 0 : theme.screenPadding;

  return (
    <View style={styles.root}>
      <StatusBar barStyle="light-content" backgroundColor={colors.background} />
      {/* Ambient brand glow at the top of every screen. */}
      <LinearGradient
        colors={['rgba(47,107,255,0.16)', 'rgba(47,107,255,0)']}
        style={styles.glow}
        pointerEvents="none"
      />
      <SafeAreaView style={styles.safe} edges={edges}>
        {scroll ? (
          <ScrollView
            style={[styles.flex, contentStyle]}
            contentContainerStyle={[
              { paddingHorizontal: padding, paddingBottom: 24 },
              contentContainerStyle,
            ]}
            showsVerticalScrollIndicator={false}
          >
            {children}
          </ScrollView>
        ) : (
          <View
            style={[styles.flex, { paddingHorizontal: padding }, contentStyle]}
          >
            {children}
          </View>
        )}
      </SafeAreaView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.background },
  safe: { flex: 1 },
  flex: { flex: 1 },
  glow: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    height: 260,
  },
});
