/** Formatting helpers — Arabic-Indic numerals and currency/units. */

const ARABIC_DIGITS = ['٠', '١', '٢', '٣', '٤', '٥', '٦', '٧', '٨', '٩'];

/** Convert Western digits in a string/number to Arabic-Indic digits. */
export function toArabicDigits(value: string | number): string {
  return String(value).replace(/[0-9]/g, (d) => ARABIC_DIGITS[Number(d)]);
}

/** Convert Arabic-Indic digits back to Western digits (for parsing input). */
export function toWesternDigits(value: string): string {
  return value.replace(/[٠-٩]/g, (d) => String(ARABIC_DIGITS.indexOf(d)));
}

/** "٤٢٠ ر.س" */
export function formatCurrency(amount: number): string {
  return `${toArabicDigits(amount.toLocaleString('en-US'))} ر.س`;
}

/** "٣٢٠ كم" */
export function formatDistanceKm(km: number): string {
  return `${toArabicDigits(km)} كم`;
}

/** Minutes -> "٤س ٣٠د" */
export function formatDuration(minutes: number): string {
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  const parts: string[] = [];
  if (h > 0) parts.push(`${toArabicDigits(h)}س`);
  if (m > 0) parts.push(`${toArabicDigits(m)}د`);
  return parts.join(' ') || '٠د';
}

/** "٣.٢ طن" */
export function formatWeightTon(kg: number): string {
  const tons = kg / 1000;
  const text = Number.isInteger(tons) ? String(tons) : tons.toFixed(1);
  return `${toArabicDigits(text)} طن`;
}
