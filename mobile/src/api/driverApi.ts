/**
 * Driver API surface. Each function is mock-first but documents the live
 * endpoint it maps to, so the backend wiring is a drop-in replacement.
 *
 * To go live: set EXPO_PUBLIC_USE_MOCK=false and implement the `request(...)`
 * branches (left as TODO) against the FastAPI routes in app/api/routes/*.
 */
import {
  USE_MOCK,
  delay,
  request,
  setAuthToken,
  ApiError,
} from './client';
import type {
  DriverProfile,
  DriverDailyStats,
  ShipmentRequest,
  ShipmentOrder,
} from './types';
import { mockDriver, mockDailyStats } from '../mock/driver';
import { mockRequests } from '../mock/requests';
import { resolveOrder } from '../mock/orders';
import { toE164 } from '../utils/validation';

export interface LoginResult {
  token: string;
  driver: DriverProfile;
}

export const driverApi = {
  /** POST /auth/login  → OTP/identity flow. Here we accept any valid number. */
  async login(rawPhone: string): Promise<LoginResult> {
    const phone = toE164(rawPhone);
    if (USE_MOCK) {
      const result: LoginResult = {
        token: `mock.${phone}.${'session'}`,
        driver: { ...mockDriver, phoneNumber: phone },
      };
      setAuthToken(result.token);
      return delay(result);
    }
    // return request<LoginResult>('/auth/login', { method: 'POST', body: JSON.stringify({ phone }) });
    throw new ApiError(501, 'Live login not wired yet');
  },

  /** GET /drivers/me */
  async getProfile(): Promise<DriverProfile> {
    if (USE_MOCK) return delay(mockDriver);
    return request<DriverProfile>('/drivers/me');
  },

  /** GET /drivers/me/stats?date=today */
  async getDailyStats(): Promise<DriverDailyStats> {
    if (USE_MOCK) return delay(mockDailyStats);
    return request<DriverDailyStats>('/drivers/me/stats');
  },

  /** PATCH /drivers/me  { is_available } — toggles online status. */
  async setAvailability(isAvailable: boolean): Promise<{ isAvailable: boolean }> {
    if (USE_MOCK) return delay({ isAvailable }, 250);
    return request('/drivers/me', {
      method: 'PATCH',
      body: JSON.stringify({ is_available: isAvailable }),
    });
  },

  /** GET /shipments/nearby — offers near the driver while online. */
  async getNearbyRequests(): Promise<ShipmentRequest[]> {
    if (USE_MOCK) return delay(mockRequests);
    return request<ShipmentRequest[]>('/shipments/nearby');
  },

  /** GET /shipments/{id} */
  async getOrder(id: string): Promise<ShipmentOrder> {
    if (USE_MOCK) return delay(resolveOrder(id));
    return request<ShipmentOrder>(`/shipments/${id}`);
  },

  /** POST /shipments/{id}/accept → assigns the shipment to this driver. */
  async acceptOrder(id: string): Promise<{ id: string; status: 'assigned' }> {
    if (USE_MOCK) return delay({ id, status: 'assigned' }, 600);
    return request(`/shipments/${id}/accept`, { method: 'POST' });
  },

  /** POST /shipments/{id}/decline */
  async declineOrder(id: string): Promise<{ id: string; status: 'declined' }> {
    if (USE_MOCK) return delay({ id, status: 'declined' }, 200);
    return request(`/shipments/${id}/decline`, { method: 'POST' });
  },
};

export type { DriverProfile, DriverDailyStats, ShipmentRequest, ShipmentOrder };
