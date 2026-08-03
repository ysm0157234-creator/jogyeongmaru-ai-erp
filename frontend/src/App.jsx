import { Navigate, Route, Routes } from "react-router-dom";
import { getToken } from "./services/api";
import Layout from "./components/Layout";
import LoginPage from "./pages/LoginPage";
import DashboardPage from "./pages/DashboardPage";
import ReportsPage from "./pages/ReportsPage";
import ReportFormPage from "./pages/ReportFormPage";
import ComingSoonPage from "./pages/ComingSoonPage";
import AIReportPage from "./pages/AIReportPage";

function ProtectedLayout() {
  if (!getToken()) {
    return <Navigate to="/login" replace />;
  }
  return <Layout />;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />

      <Route element={<ProtectedLayout />}>
        <Route index element={<DashboardPage />} />
        <Route path="reports" element={<ReportsPage />} />
        <Route path="reports/new" element={<ReportFormPage />} />
        <Route path="reports/:id/edit" element={<ReportFormPage />} />
        <Route path="inventory" element={<ComingSoonPage title="재고관리" />} />
        <Route path="partners" element={<ComingSoonPage title="거래처관리" />} />
        <Route path="export" element={<ComingSoonPage title="수출입관리" />} />
        <Route path="ai-reports" element={<AIReportPage />} />
        <Route path="automation" element={<ComingSoonPage title="정부 사이트 자동입력" />} />
        <Route path="settings" element={<ComingSoonPage title="설정" />} />
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
