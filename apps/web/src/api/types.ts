// Types of the API responses used by the web app (see apps/api/app/schemas.py).

export type Role = "analyst" | "manager" | "admin";

export interface User {
  id: number;
  email: string;
  full_name: string;
  role: Role;
  is_active: boolean;
  created_at: string;
}

export const ROLES: Role[] = ["analyst", "manager", "admin"];

export interface NewUser {
  email: string;
  full_name: string;
  role: Role;
  password: string; // temporary; the user changes it on "My account"
}

export interface TokenResponse {
  access_token: string;
  token_type: "bearer";
  expires_at: string;
  user: User;
}

export type StockStatus = "out_of_stock" | "at_risk" | "ok" | "excess";

export interface DashboardKpis {
  label: string;
  inventory: {
    products: number;
    warehouses: number;
    units_on_hand: number;
    stock_value: number;
  };
  stock_status: Record<StockStatus | "unassessed", number> | null;
  stock_status_note: string | null;
  forecast_run_id: number | null;
  pending_recommendations: { reorder: number; transfer: number };
  purchase_orders: { open: number; overdue: number };
  supplier_ratings: { good: number; watch: number; at_risk: number; not_rated: number };
}

// --- P6-T2 screens -------------------------------------------------------------

export interface Warehouse {
  id: number;
  code: string;
  name: string;
  city: string;
  capacity_units: number;
}

export interface Supplier {
  id: number;
  code: string;
  name: string;
  country: string;
  lead_time_days: number;
  lead_time_std_days: string; // a decimal sent as text
}

export interface Product {
  id: number;
  sku: string;
  name: string;
  category: string;
}

export interface Risk {
  product_id: number;
  sku: string;
  warehouse_id: number;
  warehouse_code: string;
  status: StockStatus;
  on_hand: number;
  on_order: number;
  position: number;
  daily_mean: number;
  reorder_point: number;
  target_level: number;
  shortfall: number;
  days_of_cover: number | null;
  lead_time_days: number;
  demand_profile: string;
}

export interface Recommendation {
  id: number;
  kind: "reorder" | "transfer";
  status: "pending" | "superseded";
  product_id: number;
  warehouse_id: number;
  source_warehouse_id: number | null;
  supplier_id: number | null;
  quantity: number;
  reason: string;
  service_level: string;
  // The numbers behind it: item (reorder) or destination + source (transfer).
  details: {
    item?: Partial<Risk>;
    destination?: Partial<Risk>;
    source?: Partial<Risk>;
  };
  created_at: string;
}

export type Rating = "good" | "watch" | "at_risk" | "not_rated";

export interface SupplierRisk {
  supplier_id: number;
  code: string;
  name: string;
  rating: Rating;
  on_time_rate: number | null;
  received_orders: number;
  on_time_orders: number;
  average_days_late: number | null;
  open_orders: number;
  overdue_orders: string[];
}

export interface PurchaseOrder {
  id: number;
  po_number: string;
  supplier_id: number;
  warehouse_id: number;
  status: "open" | "received" | "cancelled";
  ordered_date: string;
  expected_date: string;
  received_date: string | null;
  lines: { product_id: number; quantity: number; unit_cost: string }[];
}

export interface ForecastRow {
  series_id: string;
  store_id: string;
  item_id: string;
  forecast_date: string;
  step: number;
  forecast: number;
  lower: number;
  upper: number;
}

export interface DeliveryRiskRun {
  id: number;
  name: string;
  dataset: string;
  model: string;
  period_start: string;
  period_end: string;
  row_count: number;
}

export interface DeliveryRiskScore {
  order_id: string;
  dispatch_date: string;
  probability: number;
  day_percentile: number;
  tier: "high" | "medium" | "low";
  alert: boolean;
  reasons: { feature: string; value: unknown; effect: number }[];
}
