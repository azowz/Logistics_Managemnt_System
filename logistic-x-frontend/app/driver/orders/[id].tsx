import React, { useCallback, useEffect, useState } from 'react';
import {
  View,
  StyleSheet,
  Pressable,
  ActivityIndicator,
  useWindowDimensions,
  ScrollView,
} from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import { LinearGradient } from 'expo-linear-gradient';
import { Ionicons } from '@expo/vector-icons';
import {
  AppText,
  RouteMap,
  CountdownBadge,
  OrderBottomSheet,
} from '../../../src/components';
import { colors, radius, spacing } from '../../../src/theme';
import { driverApi, USE_MOCK, errorMessage } from '../../../src/api';
import type { ShipmentOrder } from '../../../src/api/types';
import { useCountdown } from '../../../src/hooks/useCountdown';

export default function OrderDetailsScreen() {
  const router = useRouter();
  const { id } = useLocalSearchParams<{ id: string }>();
  const { width, height } = useWindowDimensions();

  const [order, setOrder] = useState<ShipmentOrder | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [accepted, setAccepted] = useState(false);
  const [accepting, setAccepting] = useState(false);

  useEffect(() => {
    let alive = true;
    setLoadError(null);
    setOrder(null);
    setAccepted(false);
    driverApi
      .getOrder(String(id))
      .then((o) => { if (alive) { setOrder(o); setAccepted(o.status === 'assigned'); } })
      .catch((error) => alive && setLoadError(errorMessage(error)));
    return () => {
      alive = false;
    };
  }, [id]);

  const goHome = useCallback(() => {
    if (router.canGoBack()) router.back();
    else router.replace('/driver/home');
  }, [router]);

  // Auto-dismiss when the offer window expires (unless already accepted).
  const onExpire = useCallback(() => {
    if (!accepted) goHome();
  }, [accepted, goHome]);

  const { remaining } = useCountdown(order?.offerWindowSeconds ?? null, onExpire, USE_MOCK && !accepted);

  const handleAccept = async () => {
    if (!order || accepting) return;
    setActionError(null);
    setAccepting(true);
    try {
      await driverApi.acceptOrder(order.id);
      setAccepted(true);
    } catch (error) {
      setActionError(errorMessage(error));
    } finally {
      setAccepting(false);
    }
  };

  const handleDecline = async () => {
    if (!order || accepting) return;
    setAccepting(true);
    setActionError(null);
    try { await driverApi.declineOrder(order.id); goHome(); }
    catch (error) { setActionError(errorMessage(error)); }
    finally { setAccepting(false); }
  };

  if (loadError) {
    return (
      <View style={styles.loading}>
        <Ionicons name="alert-circle-outline" size={44} color={colors.warning} />
        <AppText variant="bodyStrong" align="center" style={{ marginTop: spacing.md }}>
          {loadError}
        </AppText>
        <Pressable onPress={goHome} style={styles.errorBtn}>
          <AppText variant="bodyStrong" tone="brand">
            العودة للرئيسية
          </AppText>
        </Pressable>
      </View>
    );
  }

  if (!order) {
    return (
      <View style={styles.loading}>
        <ActivityIndicator color={colors.primary} size="large" />
        <AppText variant="caption" tone="secondary" style={{ marginTop: spacing.md }}>
          جاري تحميل تفاصيل الطلب...
        </AppText>
      </View>
    );
  }

  return (
    <View style={styles.root}>
      {/* Full-screen route map background */}
      <View style={StyleSheet.absoluteFill}>
        {order.origin && order.destination ? <RouteMap
          origin={order.origin}
          destination={order.destination}
          waypoints={order.waypoints}
          width={width}
          height={height}
        /> : <AppText align="center" tone="muted" style={{ marginTop: 100 }}>إحداثيات المسار غير متاحة</AppText>}
        {/* Bottom fade so the sheet reads cleanly over the map */}
        <LinearGradient
          colors={['transparent', 'rgba(9,13,20,0.55)', colors.background]}
          locations={[0, 0.55, 1]}
          style={styles.fade}
          pointerEvents="none"
        />
      </View>

      {/* Top overlay: back + reference + countdown */}
      <SafeAreaView edges={['top']} style={styles.topBar}>
        <Pressable
          accessibilityLabel="رجوع"
          onPress={goHome}
          style={({ pressed }) => [styles.circleBtn, pressed && styles.pressed]}
        >
          <Ionicons name="arrow-forward" size={22} color={colors.textPrimary} />
        </Pressable>

        <View style={styles.refPill}>
          <Ionicons name="document-text-outline" size={14} color={colors.textSecondary} />
          <AppText variant="caption" tone="secondary">
            عرض شحنة {order.referenceCode}
          </AppText>
        </View>

        {accepted ? (
          <View style={styles.circleBtn}>
            <Ionicons name="checkmark" size={22} color={colors.success} />
          </View>
        ) : order.offerWindowSeconds !== null ? (
          <CountdownBadge remaining={remaining} total={order.offerWindowSeconds} size={56} />
        ) : null}
      </SafeAreaView>

      {/* Floating summary sheet — scrolls within a bounded height so the full
          summary stays reachable on small screens (SE-class devices). */}
      <SafeAreaView edges={['bottom']} style={styles.sheetWrap}>
        <ScrollView
          style={{ maxHeight: height * 0.82 }}
          showsVerticalScrollIndicator={false}
          bounces={false}
        >
          {actionError ? <AppText align="center" tone="danger">{actionError}</AppText> : null}
          <OrderBottomSheet
            order={order}
            accepted={accepted}
            accepting={accepting}
            onAccept={handleAccept}
            onIgnore={handleDecline}
          />
        </ScrollView>
      </SafeAreaView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.background },
  loading: {
    flex: 1,
    backgroundColor: colors.background,
    alignItems: 'center',
    justifyContent: 'center',
    padding: spacing.xxl,
  },
  errorBtn: {
    marginTop: spacing.xl,
    paddingHorizontal: spacing.xl,
    paddingVertical: spacing.md,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.borderStrong,
  },
  fade: { position: 'absolute', left: 0, right: 0, bottom: 0, height: '70%' },
  topBar: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: spacing.xl,
    paddingTop: spacing.sm,
  },
  circleBtn: {
    width: 46,
    height: 46,
    borderRadius: 23,
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.border,
    alignItems: 'center',
    justifyContent: 'center',
  },
  pressed: { opacity: 0.7 },
  refPill: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
    backgroundColor: 'rgba(18,24,33,0.9)',
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.pill,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  sheetWrap: {
    position: 'absolute',
    left: 0,
    right: 0,
    bottom: 0,
  },
});
