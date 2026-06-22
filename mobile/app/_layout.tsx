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
              <Stack.Screen name="driver/home" />
              <Stack.Screen
                name="driver/orders/[id]"
                options={{ animation: 'slide_from_bottom', presentation: 'card' }}
              />
              </Stack>
            </View>
          </SessionProvider>
        </ErrorBoundary>
      </SafeAreaProvider>
    </GestureHandlerRootView>
  );
}
