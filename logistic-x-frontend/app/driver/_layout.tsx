import React from 'react';
import { Redirect, Slot } from 'expo-router';
import { ActivityIndicator } from 'react-native';
import { useSession } from '../../src/store/session';
import { colors } from '../../src/theme';

export default function DriverLayout() {
  const { driver, restoring } = useSession();
  if (restoring) return <ActivityIndicator color={colors.primary} />;
  if (!driver) return <Redirect href="/auth/login" />;
  return <Slot />;
}
