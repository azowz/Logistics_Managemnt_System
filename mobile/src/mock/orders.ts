import type { ShipmentOrder } from '../api/types';

const RIYADH = { lat: 24.7136, lng: 46.6753 };
const JEDDAH = { lat: 21.4858, lng: 39.1925 };

/**
 * Order details keyed by request/order id. The default `order_offer`
 * record matches the spec's example offer screen.
 */
export const mockOrders: Record<string, ShipmentOrder> = {
  order_offer: {
    id: 'order_offer',
    referenceCode: 'SHP-2025',
    status: 'ready',
    distanceKm: 420,
    durationMinutes: 270, // ٤س ٣٠د
    priceSar: 420,
    requiredVehicleLabel: 'شاحنة جافة ٦م',
    weightKg: 3200, // ٣.٢ طن
    cargoType: 'تمور معبأة',
    pickupLabel: 'مستودع التمر',
    pickupCity: 'الرياض',
    dropoffLabel: 'مركز توزيع جدة',
    dropoffCity: 'جدة',
    origin: RIYADH,
    destination: JEDDAH,
    waypoints: [
      { lat: 24.09, lng: 44.4 },
      { lat: 23.5, lng: 42.1 },
      { lat: 22.3, lng: 40.2 },
    ],
    company: {
      id: 'cmp_fajr',
      name: 'شركة الفجر اللوجستية',
      rating: 4.8,
      shipmentsCount: 120,
      logoInitials: 'الفجر',
    },
    offerWindowSeconds: 15,
  },
};

/** Map a nearby-request id onto a full order, falling back to the demo offer. */
export function resolveOrder(id: string): ShipmentOrder {
  return mockOrders[id] ?? { ...mockOrders.order_offer, id };
}
