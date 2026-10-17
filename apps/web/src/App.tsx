import { Route, Routes } from "react-router-dom";

import { RequireAdmin, RequireAuth } from "./auth/AuthContext";
import { Layout } from "./components/Layout";
import { AccountPage } from "./pages/AccountPage";
import { DeliveryRiskPage } from "./pages/DeliveryRiskPage";
import { ForecastsPage } from "./pages/ForecastsPage";
import { LoginPage } from "./pages/LoginPage";
import { OverviewPage } from "./pages/OverviewPage";
import { RecommendationsPage } from "./pages/RecommendationsPage";
import { RisksPage } from "./pages/RisksPage";
import { SuppliersPage } from "./pages/SuppliersPage";
import { UsersPage } from "./pages/UsersPage";

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        <Route index element={<OverviewPage />} />
        <Route path="risks" element={<RisksPage />} />
        <Route path="recommendations" element={<RecommendationsPage />} />
        <Route path="suppliers" element={<SuppliersPage />} />
        <Route path="forecasts" element={<ForecastsPage />} />
        <Route path="delivery-risk" element={<DeliveryRiskPage />} />
        <Route path="account" element={<AccountPage />} />
        <Route
          path="users"
          element={
            <RequireAdmin>
              <UsersPage />
            </RequireAdmin>
          }
        />
      </Route>
      <Route path="*" element={<p role="alert">Page not found.</p>} />
    </Routes>
  );
}
