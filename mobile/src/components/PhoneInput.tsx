import React, { useState } from 'react';
import { View, TextInput, StyleSheet, Image } from 'react-native';
import { AppText } from './AppText';
import { colors, radius, spacing, fonts } from '../theme';
import { toWesternDigits } from '../utils/format';

interface PhoneInputProps {
  value: string;
  onChangeText: (value: string) => void;
  error?: string | null;
  /** Show error styling only after the field is touched/submitted. */
  showError?: boolean;
}

/**
 * Saudi phone field. Fixed +966 country chip on the leading (right) edge,
 * digits entered LTR. Strips non-digits and the local leading zero.
 */
export function PhoneInput({
  value,
  onChangeText,
  error,
  showError,
}: PhoneInputProps) {
  const [focused, setFocused] = useState(false);
  const hasError = showError && !!error;

  const handleChange = (text: string) => {
    let digits = toWesternDigits(text).replace(/\D/g, '');
    if (digits.startsWith('0')) digits = digits.slice(1);
    onChangeText(digits.slice(0, 9));
  };

  return (
    <View>
      <View
        style={[
          styles.row,
          focused && styles.focused,
          hasError && styles.errored,
        ]}
      >
        {/* Country code chip (leading edge in RTL = right side). */}
        <View style={styles.code}>
          <AppText variant="micro" tone="secondary">
            🇸🇦
          </AppText>
          <AppText variant="bodyStrong" tone="primary">
            +966
          </AppText>
        </View>
        <View style={styles.divider} />
        <TextInput
          value={value}
          onChangeText={handleChange}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          keyboardType="number-pad"
          placeholder="5X XXX XXXX"
          placeholderTextColor={colors.textMuted}
          maxLength={9}
          style={styles.input}
          textContentType="telephoneNumber"
          autoComplete="tel"
        />
      </View>
      {hasError ? (
        <AppText variant="caption" tone="danger" style={styles.errorText}>
          {error}
        </AppText>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    height: 58,
    backgroundColor: colors.card,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    paddingHorizontal: spacing.lg,
  },
  focused: {
    borderColor: colors.primary,
    backgroundColor: colors.cardElevated,
  },
  errored: { borderColor: colors.danger },
  code: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
  },
  divider: {
    width: 1,
    height: 24,
    backgroundColor: colors.border,
    marginHorizontal: spacing.md,
  },
  input: {
    flex: 1,
    color: colors.textPrimary,
    fontFamily: fonts.bold,
    fontSize: 18,
    letterSpacing: 1,
    textAlign: 'left',
    writingDirection: 'ltr',
  },
  errorText: { marginTop: spacing.sm, paddingHorizontal: spacing.xs },
});
