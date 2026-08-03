import {
  Bot,
  Boxes,
  Building2,
  FileText,
  LayoutDashboard,
  LogOut,
  Settings,
  Ship,
} from "lucide-react";
import { NavLink, useNavigate } from "react-router-dom";
import { clearToken } from "../services/api";

const menus = [
  ["/", "대시보드", LayoutDashboard],
  ["/reports", "생산·판매 신고", FileText],
  ["/inventory", "재고관리", Boxes],
  ["/partners", "거래처관리", Building2],
  ["/export", "수출입관리", Ship],
  ["/automation", "자동신고", Bot],
  ["/settings", "설정", Settings],
];

export default function Layout({ children }) {
  const navigate = useNavigate();

  function logout() {
    clearToken();
    navigate("/login");
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">JM</div>
          <div>
            <strong>조경마루 AI</strong>
            <small>ERP System</small>
          </div>
        </div>

        <nav className="menu">
          {menus.map(([to, label, Icon]) => (
            <NavLink
              key={to}
              to={to}
              end={to === "/"}
              className={({ isActive }) => `menu-item ${isActive ? "active" : ""}`}
            >
              <Icon size={18} />
              <span>{label}</span>
            </NavLink>
          ))}
        </nav>

        <button className="logout-button" onClick={logout}>
          <LogOut size={18} />
          로그아웃
        </button>
      </aside>

      <main className="main-content">{children}</main>
    </div>
  );
}
