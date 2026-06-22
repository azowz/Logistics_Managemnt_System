import type { ShipmentRequest } from '../api/types';

// Approximate city coordinates (lat/lng) for route previews.
const RIYADH = { lat: 24.7136, lng: 46.6753 };
const QASSIM = { lat: 26.3267, lng: 43.975 };
const KHARJ = { lat: 24.1556, lng: 47.3122 };
const DAMMAM = { lat: 26.4207, lng: 50.0888 };

export const mockRequests: ShipmentRequest[] = [
  {
    id: 'req_1042',
    referenceCode: 'SHP-1042',
    originCity: 'الرياض',
    destinationCity: 'القصيم',
    origin: RIYADH,
    destination: QASSIM,
    cargoType: 'مواد غذائية',
    distanceKm: 320,
    weightKg: 12000,
    priceSar: 380,
    requiredVehicleLabel: 'شاحنة جافة',
    postedMinutesAgo: 3,
    badge: 'عاجل',
  },
  {
    id: 'req_1043',
    referenceCode: 'SHP-1043',
    originCity: 'الرياض',
    destinationCity: 'الخرج',
    origin: RIYADH,
    destination: KHARJ,
    cargoType: 'مواد بناء',
    distanceKm: 85,
    weightKg: 50000,
    priceSar: 220,
    requiredVehicleLabel: 'شاحنة مسطحة',
    postedMinutesAgo: 8,
  },
  {
    id: 'req_1044',
    referenceCode: 'SHP-1044',
    originCity: 'الرياض',
    destinationCity: 'الدمام',
    origin: RIYADH,
    destination: DAMMAM,
    cargoType: 'إلكترونيات',
    distanceKm: 410,
    weightKg: 8000,
    priceSar: 520,
    requiredVehicleLabel: 'شاحنة جافة',
    postedMinutesAgo: 14,
  },
];
