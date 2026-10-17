// Page frame: header with the data badge and the user, navigation, content.

import { NavLink, Outlet } from "react-router-dom";

import type { Role } from "../api/types";
import { atLeast, useAuth } from "../auth/AuthContext";
import { DataBadge } from "./DataBadge";

// Pages each role sees; the API checks the role on every call anyway.
const PAGES: { to: string; label: string; minRole: Role }[] = [
  { to: "/", label: "Overview", minRole: "analyst" },
  { to: "/risks", label: "Stock risks", minRole: "analyst" },
  { to: "/recommendations", label: "Recommendations", minRole: "analyst" },
  { to: "/suppliers", label: "Suppliers & orders", minRole: "analyst" },
  { to: "/forecasts", label: "Forecasts", minRole: "analyst" },
  { to: "/delivery-risk", label: "Delivery risk", minRole: "analyst" },
  { to: "/copilot", label: "Ask the copilot", minRole: "analyst" },
  { to: "/audit", label: "Audit log", minRole: "manager" },
  { to: "/users", label: "Users", minRole: "admin" },
  { to: "/account", label: "My account", minRole: "analyst" },
];

export function Layout() {
  const { user, logout } = useAuth();
  return (
    <div className="layout">
      <header className="header">
        <span className="brand">ChainPilot AI</span>
        <DataBadge />
        <span className="spacer" />
        {user && (
          <span className="who">
            {user.full_name} <span className="role">({user.role})</span>
          </span>
        )}
        <button type="button" onClick={() => void logout()}>
          Log out
        </button>
      </header>
      <nav aria-label="Main" className="nav">
        {PAGES.filter((page) => user && atLeast(user.role, page.minRole)).map((page) => (
          <NavLink key={page.to} to={page.to} end>
            {page.label}
          </NavLink>
        ))}
      </nav>
      <main className="main">
        <Outlet />
      </main>
    </div>
  );
}
