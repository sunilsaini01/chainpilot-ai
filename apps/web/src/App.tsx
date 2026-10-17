import { Route, Routes } from "react-router-dom";

import { RequireAuth, RequireRole } from "./auth/AuthContext";
import { Layout } from "./components/Layout";
import { AccountPage } from "./pages/AccountPage";
import { AuditPage } from "./pages/AuditPage";
import { CopilotPage } from "./pages/CopilotPage";
import { DeliveryRiskPage } from "./pages/DeliveryRiskPage";
import { ForecastsPage } from "./pages/ForecastsPage";
import { LoginPage } from "./pages/LoginPage";
import { NotFoundPage } from "./pages/NotFoundPage";
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
        <Route path="copilot" element={<CopilotPage />} />
        <Route
          path="audit"
          element={
            <RequireRole role="manager">
              <AuditPage />
            </RequireRole>
          }
        />
        <Route path="account" element={<AccountPage />} />
        <Route
          path="users"
          element={
            <RequireRole role="admin">
              <UsersPage />
            </RequireRole>
          }
        />
      </Route>
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  );
}
