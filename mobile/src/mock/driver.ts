import type { DriverProfile, DriverDailyStats } from '../api/types';

export const mockDriver: DriverProfile = {
  id: 'drv_8f21',
  userId: 'usr_5530',
  fullName: 'سعود بن عبدالله القحطاني',
  greetingName: 'سعود',
  phoneNumber: '+966512345678',
  vehicleType: 'dry',
  vehicleTypeLabel: 'شاحنة جافة',
  plateNumber: 'TRK-118',
  rating: 4.9,
  isAvailable: true,
  homeCity: 'الرياض',
};

export const mockDailyStats: DriverDailyStats = {
  earningsSar: 480,
  trips: 6,
  onlineHours: 5.2,
  distanceKm: 312,
  date: '2026-06-20',
};
