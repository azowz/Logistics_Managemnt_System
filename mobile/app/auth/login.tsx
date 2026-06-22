import React, { useState } from 'react';
import {
  View,
  StyleSheet,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
} from 'react-native';
import { useRouter } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import { LinearGradient } from 'expo-linear-gradient';
import {
  AppLayout,
  AppText,
  PhoneInput,
  PrimaryButton,
  SecondaryButton,
} from '../../src/components';
import { colors, radius, spacing } from '../../src/theme';
import { driverApi } from '../../src/api';
import { useSession } from '../../src/store/session';
import { isValidSaudiMobile, saudiMobileError } from '../../src/utils/validation';

export default function LoginScreen() {
  const router = useRouter();
  const { signIn } = useSession();

  const [phone, setPhone] = useState('');
  const [submitted, setSubmitted] = useState(false);
  const [loading, setLoading] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const error = saudiMobileError(phone);
  const canSubmit = isValidSaudiMobile(phone);

  const handleLogin = async () => {
    setSubmitted(true);
    setSubmitError(null);
    if (!canSubmit || loading) return;
    setLoading(true);
    try {
      const { token, driver } = await driverApi.login(phone);
      await signIn(driver, token);
      router.replace('/driver/home');
    } catch {
      setSubmitError('تعذّر تسجيل الدخول. تحقق من اتصالك وحاول مرة أخرى.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <AppLayout>
      <KeyboardAvoidingView
        style={styles.flex}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      >
        <ScrollView
          contentContainerStyle={styles.scroll}
          keyboardShouldPersistTaps="handled"
          showsVerticalScrollIndicator={false}
        >
          {/* Brand */}
          <View style={styles.brand}>
            <LinearGradient
              colors={[colors.primary, '#1E4FD8']}
              start={{ x: 0, y: 0 }}
              end={{ x: 1, y: 1 }}
              style={styles.logo}
            >
              <Ionicons name="bus" size={40} color={colors.textOnPrimary} />
            </LinearGradient>
            <AppText variant="display" align="center" style={styles.appName}>
              مسار
            </AppText>
            <AppText variant="body" tone="secondary" align="center">
              بوابة السائقين للشحن البري
            </AppText>
          </View>

          {/* Login form */}
          <View style={styles.form}>
            <AppText variant="bodyStrong" style={styles.label}>
              رقم الجوال
            </AppText>
            <PhoneInput
              value={phone}
              onChangeText={(v) => {
                setPhone(v);
                if (submitError) setSubmitError(null);
              }}
              error={error}
              // Surface format errors on submit, or as soon as a full 9-digit
              // number is entered that still isn't valid (real-time, not noisy).
              showError={submitted || (phone.length >= 9 && !canSubmit)}
            />

            {submitError ? (
              <View style={styles.banner}>
                <Ionicons name="alert-circle" size={18} color={colors.danger} />
                <AppText variant="caption" tone="danger" style={styles.flex}>
                  {submitError}
                </AppText>
              </View>
            ) : null}

            <PrimaryButton
              label="تسجيل الدخول"
              onPress={handleLogin}
              loading={loading}
              disabled={submitted && !canSubmit}
              style={styles.primaryBtn}
            />

            <View style={styles.divider}>
              <View style={styles.line} />
              <AppText variant="caption" tone="muted">
                أو
              </AppText>
              <View style={styles.line} />
            </View>

            <SecondaryButton
              label="الدخول عبر نفاذ الوطني الموحد"
              icon="shield-checkmark-outline"
              onPress={() => {}}
            />
          </View>

          {/* Register link */}
          <Pressable style={styles.registerRow} onPress={() => {}}>
            <AppText variant="body" tone="secondary">
              سائق جديد؟{' '}
            </AppText>
            <AppText variant="bodyStrong" tone="brand">
              سجل الآن
            </AppText>
          </Pressable>

          <AppText variant="micro" tone="muted" align="center" style={styles.terms}>
            بالمتابعة، أنت توافق على شروط الخدمة وسياسة الخصوصية
          </AppText>
        </ScrollView>
      </KeyboardAvoidingView>
    </AppLayout>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  scroll: { flexGrow: 1, justifyContent: 'center', paddingVertical: spacing.xxl },
  brand: { alignItems: 'center', gap: spacing.sm, marginBottom: spacing.huge },
  logo: {
    width: 88,
    height: 88,
    borderRadius: radius.xxl,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: spacing.md,
    shadowColor: colors.primary,
    shadowOpacity: 0.5,
    shadowRadius: 24,
    shadowOffset: { width: 0, height: 12 },
    elevation: 12,
  },
  appName: { marginTop: spacing.sm },
  form: { gap: spacing.lg },
  banner: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    backgroundColor: colors.dangerSoft,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  label: { paddingHorizontal: spacing.xs },
  primaryBtn: { marginTop: spacing.sm },
  divider: { flexDirection: 'row', alignItems: 'center', gap: spacing.md },
  line: { flex: 1, height: 1, backgroundColor: colors.border },
  registerRow: {
    flexDirection: 'row',
    justifyContent: 'center',
    alignItems: 'center',
    marginTop: spacing.xxl,
  },
  terms: { marginTop: spacing.lg, paddingHorizontal: spacing.xl },
});
