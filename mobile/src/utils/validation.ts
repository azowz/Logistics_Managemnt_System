import { toWesternDigits } from './format';

/**
 * Saudi mobile validation.
 * Accepts what a driver might actually type: 05XXXXXXXX, 5XXXXXXXX,
 * +9665XXXXXXXX, or 9665XXXXXXXX (with Arabic digits too).
 * Canonical mobile = 9 digits starting with 5 (national significant number).
 */
const NSN = /^5\d{8}$/;

export function normalizeSaudiMobile(raw: string): string {
  let digits = toWesternDigits(raw).replace(/\D/g, '');
  if (digits.startsWith('966')) digits = digits.slice(3);
  if (digits.startsWith('0')) digits = digits.slice(1);
  return digits;
}

export function isValidSaudiMobile(raw: string): boolean {
  return NSN.test(normalizeSaudiMobile(raw));
}

/** E.164 phone for the API, e.g. "+966512345678". */
export function toE164(raw: string): string {
  return `+966${normalizeSaudiMobile(raw)}`;
}

/** Returns an Arabic error message, or null when valid. */
export function saudiMobileError(raw: string): string | null {
  const nsn = normalizeSaudiMobile(raw);
  if (nsn.length === 0) return 'الرجاء إدخال رقم الجوال';
  if (!/^5/.test(nsn)) return 'يجب أن يبدأ الرقم بالرقم ٥';
  if (nsn.length !== 9) return 'رقم الجوال غير مكتمل';
  return null;
}
