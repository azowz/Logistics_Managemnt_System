import React, { useCallback } from 'react';
import { View } from 'react-native';
import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import * as SplashScreen from 'expo-splash-screen';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import { SessionProvider } from '../src/store/session';
import { ErrorBoundary } from '../src/components';
import { useAppBootstrap } from '../src/hooks/useAppBootstrap';
import { colors } from '../src/theme';
import { AppText } from '../src/components';
import { USE_MOCK } from '../src/api';

SplashScreen.preventAutoHideAsync().catch(() => {});

export default function RootLayout() {
  const { ready } = useAppBootstrap();

  const onLayout = useCallback(() => {
    if (ready) SplashScreen.hideAsync().catch(() => {});
  }, [ready]);

  if (!ready) return null;

  return (
    <GestureHandlerRootView style={{ flex: 1, backgroundColor: colors.background }}>
      <SafeAreaProvider>
        <ErrorBoundary>
          <SessionProvider>
            <View style={{ flex: 1, backgroundColor: colors.background }} onLayout={onLayout}>
              {USE_MOCK ? <AppText align="center" style={{ color: colors.warning }}>وضع تجريبي — بيانات غير حقيقية</AppText> : null}
              <StatusBar style="light" />
              <Stack
              screenOptions={{
                headerShown: false,
                contentStyle: { backgroundColor: colors.background },
                animation: 'fade',
              }}
            >
              <Stack.Screen name="index" />
              <Stack.Screen name="auth/login" />
              <Stack.Screen name="driver" />
              </Stack>
            </View>
          </SessionProvider>
        </ErrorBoundary>
      </SafeAreaProvider>
    </GestureHandlerRootView>
  );
}
