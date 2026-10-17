// Page frame: header with the data badge and the user, navigation, content.

import { NavLink, Outlet } from "react-router-dom";

import { useAuth } from "../auth/AuthContext";
import { DataBadge } from "./DataBadge";

// "Users" is listed only for admins; the API checks the role on every call anyway.
const PAGES = [
  { to: "/", label: "Overview", adminOnly: false },
  { to: "/risks", label: "Stock risks", adminOnly: false },
  { to: "/recommendations", label: "Recommendations", adminOnly: false },
  { to: "/suppliers", label: "Suppliers & orders", adminOnly: false },
  { to: "/forecasts", label: "Forecasts", adminOnly: false },
  { to: "/delivery-risk", label: "Delivery risk", adminOnly: false },
  { to: "/users", label: "Users", adminOnly: true },
  { to: "/account", label: "My account", adminOnly: false },
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
        {PAGES.filter((page) => !page.adminOnly || user?.role === "admin").map((page) => (
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
