/**
 * Domain types for the driver app.
 *
 * These mirror the FastAPI backend (app/models/*.py) so the mock layer can be
 * swapped for real HTTP responses with minimal churn:
 *  - ShipmentStatus matches app/models/enums.py::ShipmentStatus
 *  - GeoPoint maps to warehouse lat/lng
 *  - ids are string UUIDs as the backend emits
 */

export type ShipmentStatus =
  | 'created'
  | 'ready'
  | 'assigned'
  | 'in_transit'
  | 'delivered'
  | 'cancelled'
  | 'returned'
  | 'failed';

/** Truck body types relevant to the driver UI. */
export type VehicleType = 'dry' | 'reefer' | 'flatbed' | 'tanker';

export interface GeoPoint {
  lat: number;
  lng: number;
}

export interface DriverProfile {
  id: string;
  userId: string;
  fullName: string;
  greetingName: string; // short name used in the header greeting
  phoneNumber: string; // E.164, e.g. +966512345678
  vehicleType: VehicleType;
  vehicleTypeLabel: string; // localized, e.g. "شاحنة جافة"
  plateNumber: string; // e.g. TRK-118
  rating: number;
  isAvailable: boolean;
  homeCity: string;
}

export interface DriverDailyStats {
  earningsSar: number;
  trips: number;
  onlineHours: number;
  distanceKm: number;
  /** ISO date the stats apply to. */
  date: string;
}

/** A nearby shipment offer surfaced on the dashboard. */
export interface ShipmentRequest {
  id: string;
  referenceCode: string;
  originCity: string;
  destinationCity: string;
  origin: GeoPoint;
  destination: GeoPoint;
  cargoType: string; // e.g. "مواد غذائية"
  distanceKm: number;
  weightKg: number;
  priceSar: number;
  requiredVehicleLabel: string;
  postedMinutesAgo: number;
  /** Tag rendered as an orange badge, e.g. "عاجل". */
  badge?: string;
}

export interface ShipperCompany {
  id: string;
  name: string;
  rating: number;
  shipmentsCount: number;
  logoInitials: string;
}

/** Full order detail behind a request (the offer screen). */
export interface ShipmentOrder {
  id: string;
  referenceCode: string;
  status: ShipmentStatus;
  distanceKm: number;
  durationMinutes: number;
  priceSar: number;
  requiredVehicleLabel: string;
  weightKg: number;
  cargoType: string;
  pickupLabel: string;
  pickupCity: string;
  dropoffLabel: string;
  dropoffCity: string;
  origin: GeoPoint;
  destination: GeoPoint;
  /** Intermediate route points for drawing a non-straight line. */
  waypoints: GeoPoint[];
  company: ShipperCompany;
  /** Seconds the driver has to accept the offer. */
  offerWindowSeconds: number;
}
