import React, { useEffect, useState } from 'react';
import { View, StyleSheet, ScrollView, RefreshControl, Pressable } from 'react-native';
import { useRouter } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import {
  AppLayout,
  AppText,
  DriverHeader,
  StatusCard,
  KPIBox,
  MapPreview,
  ShipmentRequestCard,
  BottomNav,
} from '../../src/components';
import type { TabKey } from '../../src/components';
import { colors, spacing } from '../../src/theme';
import { driverApi } from '../../src/api';
import type { DriverDailyStats, ShipmentRequest } from '../../src/api/types';
import { useSession } from '../../src/store/session';
import { mockDriver } from '../../src/mock/driver';
import { toArabicDigits } from '../../src/utils/format';

export default function HomeScreen() {
  const router = useRouter();
  const { driver: sessionDriver, isOnline, setOnline } = useSession();
  // Fall back to mock so deep-linking straight to /driver/home still renders.
  const driver = sessionDriver ?? mockDriver;

  const [stats, setStats] = useState<DriverDailyStats | null>(null);
  const [requests, setRequests] = useState<ShipmentRequest[]>([]);
  const [refreshing, setRefreshing] = useState(false);
  const [loadError, setLoadError] = useState(false);
  const [tab, setTab] = useState<TabKey>('home');

  const load = async () => {
    try {
      const [s, r] = await Promise.all([
        driverApi.getDailyStats(),
        driverApi.getNearbyRequests(),
      ]);
      setStats(s);
      setRequests(r);
      setLoadError(false);
    } catch {
      setLoadError(true);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const onRefresh = async () => {
    setRefreshing(true);
    try {
      await load();
    } finally {
      setRefreshing(false);
    }
  };

  const openOrder = (id: string) =>
    router.push({ pathname: '/driver/orders/[id]', params: { id } });

  return (
    <AppLayout bleed edges={['top']}>
      <ScrollView
        contentContainerStyle={styles.scroll}
        showsVerticalScrollIndicator={false}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={onRefresh}
            tintColor={colors.primary}
          />
        }
      >
        <DriverHeader
          driver={driver}
          greeting="مساء"
          notificationCount={3}
          onPressNotifications={() => {}}
        />

        <View style={styles.section}>
          <StatusCard isOnline={isOnline} onToggle={setOnline} />
        </View>

        {/* KPI grid */}
        <View style={styles.kpiGrid}>
          <KPIBox
            icon="cash-outline"
            tint={colors.success}
            label="أرباح اليوم"
            value={toArabicDigits(stats?.earningsSar ?? 0)}
            unit="ريال"
          />
          <KPIBox
            icon="cube-outline"
            tint={colors.primary}
            label="رحلات اليوم"
            value={toArabicDigits(stats?.trips ?? 0)}
          />
          <KPIBox
            icon="time-outline"
            tint={colors.warning}
            label="ساعات الاتصال"
            value={toArabicDigits(stats?.onlineHours ?? 0)}
            unit="ساعة"
          />
          <KPIBox
            icon="navigate-outline"
            tint="#9B7DFF"
            label="المسافة"
            value={toArabicDigits(stats?.distanceKm ?? 0)}
            unit="كم"
          />
        </View>

        {/* Nearby requests */}
        <View style={styles.sectionHeader}>
          <AppText variant="h2">طلبات قريبة منك</AppText>
          {isOnline ? (
            <View style={styles.liveTag}>
              <View style={styles.liveDot} />
              <AppText variant="micro" tone="success">
                مباشر
              </AppText>
            </View>
          ) : null}
        </View>

        {loadError ? (
          <Pressable style={styles.errorBanner} onPress={onRefresh}>
            <Ionicons name="cloud-offline-outline" size={18} color={colors.danger} />
            <AppText variant="caption" tone="danger" style={styles.flex}>
              تعذّر تحميل البيانات
            </AppText>
            <AppText variant="caption" tone="brand">
              إعادة المحاولة
            </AppText>
          </Pressable>
        ) : null}

        {isOnline ? (
          <>
            {requests[0] ? (
              <MapPreview
                origin={requests[0].origin}
                destination={requests[0].destination}
                originLabel={requests[0].originCity}
                destinationLabel={requests[0].destinationCity}
              />
            ) : null}

            <View style={styles.requestList}>
              {requests.map((req) => (
                <ShipmentRequestCard
                  key={req.id}
                  request={req}
                  onPress={(r) => openOrder(r.id)}
                />
              ))}
            </View>
          </>
        ) : (
          <View style={styles.offline}>
            <Ionicons name="cloud-offline-outline" size={36} color={colors.textMuted} />
            <AppText variant="bodyStrong" tone="secondary" align="center">
              أنت غير متصل حالياً
            </AppText>
            <AppText variant="caption" tone="muted" align="center">
              فعّل الاتصال من الأعلى لاستقبال طلبات الشحن القريبة
            </AppText>
          </View>
        )}
      </ScrollView>

      <BottomNav active={tab} onChange={setTab} />
    </AppLayout>
  );
}

const styles = StyleSheet.create({
  scroll: {
    paddingHorizontal: spacing.xl,
    paddingTop: spacing.md,
    paddingBottom: spacing.xxl,
    gap: spacing.lg,
  },
  section: { marginTop: spacing.xs },
  kpiGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.md,
  },
  sectionHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginTop: spacing.sm,
  },
  liveTag: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
    backgroundColor: colors.successSoft,
    borderRadius: 999,
    paddingHorizontal: spacing.md,
    paddingVertical: 4,
  },
  liveDot: { width: 7, height: 7, borderRadius: 4, backgroundColor: colors.success },
  flex: { flex: 1 },
  errorBanner: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    backgroundColor: colors.dangerSoft,
    borderRadius: 14,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.md,
  },
  requestList: { gap: spacing.md },
  offline: {
    alignItems: 'center',
    gap: spacing.sm,
    paddingVertical: spacing.huge,
  },
});
