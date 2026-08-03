import {
  Bot,
  Boxes,
  Building2,
  ChevronRight,
  FileText,
  LayoutDashboard,
  LogOut,
  Settings,
  Ship,
  Sparkles,
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
          <div className="brand-mark">
            <Sparkles size={20} />
          </div>
          <div>
            <strong>조경마루 AI</strong>
            <small>Smart ERP</small>
          </div>
        </div>

        <div className="sidebar-section-label">업무 메뉴</div>

        <nav className="menu">
          {menus.map(([to, label, Icon]) => (
            <NavLink
              key={to}
              to={to}
              end={to === "/"}
              className={({ isActive }) => `menu-item ${isActive ? "active" : ""}`}
            >
              <span className="menu-icon"><Icon size={18} /></span>
              <span>{label}</span>
              <ChevronRight size={15} className="menu-chevron" />
            </NavLink>
          ))}
        </nav>

        <div className="sidebar-profile">
          <div className="avatar">JM</div>
          <div className="sidebar-profile-text">
            <strong>관리자</strong>
            <span>admin@jogyeongmaru.co.kr</span>
          </div>
        </div>

        <button className="logout-button" onClick={logout}>
          <LogOut size={18} />
          로그아웃
        </button>
      </aside>

      <main className="main-content">
        <div className="content-container">{children}</div>
      </main>
    </div>
  );
}
