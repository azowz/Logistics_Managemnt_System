import { USE_MOCK, delay, apiRequest, setAuthToken, ApiError } from './client';
import type { components } from './generated';
import type { DriverProfile, DriverDailyStats, ShipmentRequest, ShipmentOrder } from './types';
import { mockDriver, mockDailyStats } from '../mock/driver';
import { mockRequests } from '../mock/requests';
import { resolveOrder } from '../mock/orders';
import { toE164 } from '../utils/validation';

export interface LoginResult { token: string; driver: DriverProfile; refreshToken?: string; }
type DriverRead = components['schemas']['DriverRead'];
type UserRead = components['schemas']['UserRead'];

export function mapDriver(driver: DriverRead, user?: UserRead): DriverProfile {
  const name = user?.full_name || 'السائق';
  return {
    id: driver.id, userId: driver.user_id, fullName: name, greetingName: name.split(' ')[0],
    phoneNumber: driver.phone_number ?? '', isAvailable: driver.is_available,
    vehicleType: null, vehicleTypeLabel: 'المركبة غير متاحة', plateNumber: '—',
    rating: null, homeCity: '—',
  };
}

export const driverApi = {
  /** Existing phone contract. The backend deliberately disables it in production. */
  async login(rawPhone: string): Promise<LoginResult> {
    const phone = toE164(rawPhone);
    if (USE_MOCK) {
      const result = { token: `mock.${phone}.session`, driver: { ...mockDriver, phoneNumber: phone } };
      setAuthToken(result.token);
      return delay(result);
    }
    const response = await apiRequest('/v1/auth/driver/login', 'post', { body: { phone } });
    setAuthToken(response.access_token);
    try {
      const user = await apiRequest('/v1/auth/me', 'get');
      return { token: response.access_token, driver: mapDriver(response.driver, user) };
    } catch (error) { setAuthToken(null); throw error; }
  },

  /** Standard JWT login, including tenant_slug; no backend authentication changes. */
  async loginWithPassword(email: string, password: string, tenantSlug: string): Promise<LoginResult> {
    const response = await apiRequest('/v1/auth/login', 'post', {
      body: { email, password, ...(tenantSlug ? { tenant_slug: tenantSlug } : {}) },
    });
    setAuthToken(response.access_token);
    try {
      const profile = await apiRequest('/v1/drivers/me', 'get');
      return { token: response.access_token, refreshToken: response.refresh_token ?? undefined,
        driver: mapDriver(profile, response.user) };
    } catch (error) { setAuthToken(null); throw error; }
  },

  async logout(refreshToken?: string): Promise<void> {
    if (!USE_MOCK) await apiRequest('/v1/auth/logout', 'post', { body: { refresh_token: refreshToken } });
  },

  async getProfile(): Promise<DriverProfile> {
    if (USE_MOCK) return delay(mockDriver);
    const [driver, user] = await Promise.all([
      apiRequest('/v1/drivers/me', 'get'), apiRequest('/v1/auth/me', 'get'),
    ]);
    return mapDriver(driver, user);
  },

  async getDailyStats(): Promise<DriverDailyStats> {
    if (USE_MOCK) return delay(mockDailyStats);
    const stats = await apiRequest('/v1/drivers/me/stats', 'get');
    return { earningsSar: stats.earnings_sar ?? 0, trips: stats.trips ?? 0,
      onlineHours: stats.online_hours ?? 0, distanceKm: stats.distance_km ?? 0, date: stats.date };
  },

  async setAvailability(isAvailable: boolean): Promise<{ isAvailable: boolean }> {
    if (USE_MOCK) return delay({ isAvailable }, 250);
    const driver = await apiRequest('/v1/drivers/me', 'patch', { body: { is_available: isAvailable } });
    return { isAvailable: driver.is_available };
  },

  async getNearbyRequests(): Promise<ShipmentRequest[]> {
    if (USE_MOCK) return delay(mockRequests);
    const offers = await apiRequest('/v1/shipments/nearby', 'get');
    return offers.map((offer) => ({
      id: offer.id, referenceCode: offer.reference_code,
      originCity: offer.origin_city ?? 'غير متاح', destinationCity: offer.destination_city ?? 'غير متاح',
      origin: null, destination: null, cargoType: offer.cargo_type ?? 'غير متاح',
      distanceKm: offer.distance_km ?? null, weightKg: offer.weight_kg,
      priceSar: offer.price_sar ?? null, requiredVehicleLabel: offer.required_vehicle_label ?? 'غير متاح',
      postedMinutesAgo: null,
    }));
  },

  async getOrder(id: string): Promise<ShipmentOrder> {
    if (USE_MOCK) return delay(resolveOrder(id));
    const shipment = await apiRequest('/v1/shipments/{shipment_id}', 'get', { params: { shipment_id: id } });
    // The existing driver contract does not expose warehouse coordinates,
    // company ratings, duration, or an offer deadline. Display them as absent.
    return {
      id: shipment.id, referenceCode: shipment.reference_code, status: shipment.status,
      distanceKm: null, durationMinutes: null, priceSar: shipment.price_sar == null ? null : Number(shipment.price_sar),
      requiredVehicleLabel: shipment.required_vehicle_type ?? 'غير متاح', weightKg: Number(shipment.weight_kg),
      cargoType: shipment.cargo_type ?? 'غير متاح', pickupLabel: 'الاستلام', pickupCity: 'غير متاح',
      dropoffLabel: 'التسليم', dropoffCity: 'غير متاح', origin: null, destination: null,
      waypoints: [], company: null, offerWindowSeconds: null,
    };
  },

  async acceptOrder(id: string): Promise<{ id: string; status: 'assigned' }> {
    if (USE_MOCK) return delay({ id, status: 'assigned' }, 600);
    const shipment = await apiRequest('/v1/shipments/{shipment_id}/accept', 'post', { params: { shipment_id: id } });
    if (shipment.status !== 'assigned') throw new ApiError(409, 'أعد تحميل حالة الشحنة.');
    return { id: shipment.id, status: shipment.status };
  },

  async declineOrder(id: string): Promise<void> {
    if (USE_MOCK) return delay(undefined, 200);
    await apiRequest('/v1/shipments/{shipment_id}/decline', 'post', { params: { shipment_id: id } });
  },
};

export type { DriverProfile, DriverDailyStats, ShipmentRequest, ShipmentOrder };
