import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../services/api";

export default function DashboardPage() {
  const [stats, setStats] = useState({
    total: 0,
    draft: 0,
    pending: 0,
    done: 0,
    production: 0,
    sales: 0,
  });
  const [reports, setReports] = useState([]);

  useEffect(() => {
    Promise.all([
      api("/api/reports/dashboard"),
      api("/api/reports"),
    ]).then(([dashboard, list]) => {
      setStats(dashboard);
      setReports(list.slice(0, 5));
    });
  }, []);

  return (
    <div>
      <header className="page-header">
        <div>
          <p className="eyebrow">OVERVIEW</p>
          <h1>대시보드</h1>
          <p className="muted">생산·판매 신고 현황을 한눈에 확인합니다.</p>
        </div>
        <Link className="primary-button link-button" to="/reports/new">
          + 신고 등록
        </Link>
      </header>

      <section className="stats-grid">
        {[
          ["전체 신고", stats.total],
          ["작성 중", stats.draft],
          ["전송 대기", stats.pending],
          ["완료", stats.done],
          ["생산 신고", stats.production],
          ["판매 신고", stats.sales],
        ].map(([label, value]) => (
          <article className="stat-card" key={label}>
            <span>{label}</span>
            <strong>{value}</strong>
          </article>
        ))}
      </section>

      <section className="panel">
        <div className="panel-header">
          <div>
            <h2>최근 신고</h2>
            <p className="muted">최근 등록된 신고 5건입니다.</p>
          </div>
          <Link to="/reports" className="text-link">전체 보기</Link>
        </div>

        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>신고일</th>
                <th>기관</th>
                <th>구분</th>
                <th>품목 / 품종</th>
                <th>수량</th>
                <th>상태</th>
              </tr>
            </thead>
            <tbody>
              {reports.length ? reports.map((report) => (
                <tr key={report.id}>
                  <td>{report.report_date}</td>
                  <td>{report.agency}</td>
                  <td>{report.report_type}</td>
                  <td>{report.item_name} / {report.variety_name}</td>
                  <td>{report.quantity.toLocaleString()} {report.unit}</td>
                  <td><span className={`status ${statusClass(report.status)}`}>{report.status}</span></td>
                </tr>
              )) : (
                <tr><td colSpan="6" className="empty-cell">등록된 신고가 없습니다.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

function statusClass(status) {
  if (status === "완료") return "done";
  if (status === "전송 대기") return "pending";
  return "draft";
}
