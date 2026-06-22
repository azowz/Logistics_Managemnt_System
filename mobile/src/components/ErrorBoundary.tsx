import React from 'react';
import { View, StyleSheet } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { AppText } from './AppText';
import { PrimaryButton } from './PrimaryButton';
import { colors, spacing } from '../theme';

interface Props {
  children: React.ReactNode;
}
interface State {
  hasError: boolean;
}

/**
 * Root error boundary — contains render/runtime errors behind a localized
 * fallback instead of white-screening the whole app.
 */
export class ErrorBoundary extends React.Component<Props, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError(): State {
    return { hasError: true };
  }

  componentDidCatch(error: unknown) {
    // Hook for Sentry/crash reporting in production.
    // eslint-disable-next-line no-console
    console.error('Unhandled UI error:', error);
  }

  reset = () => this.setState({ hasError: false });

  render() {
    if (!this.state.hasError) return this.props.children;
    return (
      <View style={styles.root}>
        <Ionicons name="warning-outline" size={48} color={colors.warning} />
        <AppText variant="h2" align="center">
          حدث خطأ غير متوقع
        </AppText>
        <AppText variant="body" tone="secondary" align="center" style={styles.body}>
          نعتذر عن الخلل. حاول مرة أخرى للمتابعة.
        </AppText>
        <PrimaryButton label="إعادة المحاولة" icon="refresh" onPress={this.reset} style={styles.btn} />
      </View>
    );
  }
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
    backgroundColor: colors.background,
    alignItems: 'center',
    justifyContent: 'center',
    padding: spacing.xxl,
    gap: spacing.md,
  },
  body: { maxWidth: 300 },
  btn: { alignSelf: 'stretch', marginTop: spacing.md },
});
