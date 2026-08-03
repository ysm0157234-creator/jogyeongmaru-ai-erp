import { Navigate, Route, Routes } from "react-router-dom";
import { getToken } from "./services/api";
import Layout from "./components/Layout";
import LoginPage from "./pages/LoginPage";
import DashboardPage from "./pages/DashboardPage";
import ReportsPage from "./pages/ReportsPage";
import ReportFormPage from "./pages/ReportFormPage";
import ComingSoonPage from "./pages/ComingSoonPage";

function ProtectedRoute({ children }) {
  return getToken() ? children : <Navigate to="/login" replace />;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/*"
        element={
          <ProtectedRoute>
            <Layout>
              <Routes>
                <Route path="/" element={<DashboardPage />} />
                <Route path="/reports" element={<ReportsPage />} />
                <Route path="/reports/new" element={<ReportFormPage />} />
                <Route path="/reports/:id/edit" element={<ReportFormPage />} />
                <Route path="/inventory" element={<ComingSoonPage title="재고관리" />} />
                <Route path="/partners" element={<ComingSoonPage title="거래처관리" />} />
                <Route path="/export" element={<ComingSoonPage title="수출입관리" />} />
                <Route path="/automation" element={<ComingSoonPage title="자동신고" />} />
                <Route path="/settings" element={<ComingSoonPage title="설정" />} />
              </Routes>
            </Layout>
          </ProtectedRoute>
        }
      />
    </Routes>
  );
}
