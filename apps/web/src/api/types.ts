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
