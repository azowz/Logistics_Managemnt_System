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
import { driverApi, USE_MOCK, errorMessage } from '../../src/api';
import type { DriverDailyStats, ShipmentRequest } from '../../src/api/types';
import { useSession } from '../../src/store/session';
import { toArabicDigits } from '../../src/utils/format';

export default function HomeScreen() {
  const router = useRouter();
  const { driver, isOnline, setOnline, signOut } = useSession();

  const [stats, setStats] = useState<DriverDailyStats | null>(null);
  const [requests, setRequests] = useState<ShipmentRequest[]>([]);
  const [refreshing, setRefreshing] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<TabKey>('home');

  const load = async () => {
    try {
      const [s, r] = await Promise.all([
        driverApi.getDailyStats(),
        driverApi.getNearbyRequests(),
      ]);
      setStats(s);
      setRequests(r);
      setLoadError(null);
    } catch (error) {
      setLoadError(errorMessage(error));
    } finally {
      setLoading(false);
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

  if (!driver) return null;

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
          notificationCount={USE_MOCK ? 3 : 0}
          onPressNotifications={() => {}}
        />

        <View style={styles.section}>
          <StatusCard isOnline={isOnline} onToggle={(value) => {
            setOnline(value).catch((error) => setLoadError(errorMessage(error)));
          }} />
        </View>

        {/* KPI grid */}
        <View style={styles.kpiGrid}>
          <KPIBox
            icon="cash-outline"
            tint={colors.success}
            label="أرباح اليوم"
            value={stats ? toArabicDigits(stats.earningsSar) : '—'}
            unit="ريال"
          />
          <KPIBox
            icon="cube-outline"
            tint={colors.primary}
            label="رحلات اليوم"
            value={stats ? toArabicDigits(stats.trips) : '—'}
          />
          <KPIBox
            icon="time-outline"
            tint={colors.warning}
            label="ساعات الاتصال"
            value={stats ? toArabicDigits(stats.onlineHours) : '—'}
            unit="ساعة"
          />
          <KPIBox
            icon="navigate-outline"
            tint="#9B7DFF"
            label="المسافة"
            value={stats ? toArabicDigits(stats.distanceKm) : '—'}
            unit="كم"
          />
        </View>

        {/* Nearby requests */}
        <View style={styles.sectionHeader}>
          <AppText variant="h2">طلبات قريبة منك</AppText>
          {isOnline && !loading && !loadError ? (
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
              {loadError}
            </AppText>
            <AppText variant="caption" tone="brand">
              إعادة المحاولة
            </AppText>
          </Pressable>
        ) : null}

        {isOnline ? (
          <>
            {requests[0]?.origin && requests[0]?.destination ? (
              <MapPreview
                origin={requests[0].origin}
                destination={requests[0].destination}
                originLabel={requests[0].originCity}
                destinationLabel={requests[0].destinationCity}
              />
            ) : null}

            <View style={styles.requestList}>
              {loading ? <AppText align="center">جاري تحميل البيانات...</AppText> : null}
              {!loading && !loadError && requests.length === 0 ?
                <AppText align="center" tone="secondary">لا توجد طلبات متاحة حالياً</AppText> : null}
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
        <Pressable accessibilityRole="button" onPress={() => signOut().catch(() => {})}>
          <AppText align="center" tone="brand">تسجيل الخروج</AppText>
        </Pressable>
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
