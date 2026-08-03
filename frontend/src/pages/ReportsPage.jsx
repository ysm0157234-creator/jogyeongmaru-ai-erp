import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { API_URL, api, getToken } from "../services/api";

export default function ReportsPage() {
  const navigate = useNavigate();
  const [reports, setReports] = useState([]);
  const [filters, setFilters] = useState({
    search: "",
    agency: "",
    report_type: "",
    status: "",
  });

  useEffect(() => {
    const timeout = setTimeout(loadReports, 150);
    return () => clearTimeout(timeout);
  }, [filters]);

  async function loadReports() {
    const params = new URLSearchParams(filters);
    setReports(await api(`/api/reports?${params}`));
  }

  async function remove(id) {
    if (!window.confirm("이 신고 자료를 삭제할까요?")) return;
    await api(`/api/reports/${id}`, { method: "DELETE" });
    loadReports();
  }

  async function downloadCsv() {
    const response = await fetch(`${API_URL}/api/reports/export.csv`, {
      headers: { Authorization: `Bearer ${getToken()}` },
    });
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "생산판매신고.csv";
    anchor.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div>
      <header className="page-header">
        <div>
          <p className="eyebrow">PRODUCTION & SALES</p>
          <h1>생산·판매 신고</h1>
          <p className="muted">신고 자료를 등록하고 관리합니다.</p>
        </div>
        <div className="header-actions">
          <button className="secondary-button" onClick={downloadCsv}>CSV 다운로드</button>
          <Link className="primary-button link-button" to="/reports/new">+ 신고 등록</Link>
        </div>
      </header>

      <section className="panel">
        <div className="filter-grid">
          <input
            placeholder="품목, 품종, 거래처, 로트번호 검색"
            value={filters.search}
            onChange={(e) => setFilters({ ...filters, search: e.target.value })}
          />
          <select value={filters.agency} onChange={(e) => setFilters({ ...filters, agency: e.target.value })}>
            <option value="">전체 기관</option>
            <option>국립종자원</option>
            <option>산림청</option>
          </select>
          <select value={filters.report_type} onChange={(e) => setFilters({ ...filters, report_type: e.target.value })}>
            <option value="">전체 구분</option>
            <option>생산 신고</option>
            <option>판매 신고</option>
          </select>
          <select value={filters.status} onChange={(e) => setFilters({ ...filters, status: e.target.value })}>
            <option value="">전체 상태</option>
            <option>작성 중</option>
            <option>전송 대기</option>
            <option>완료</option>
          </select>
        </div>

        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>신고일</th>
                <th>기관</th>
                <th>구분</th>
                <th>품목</th>
                <th>품종</th>
                <th>규격</th>
                <th>수량</th>
                <th>거래처</th>
                <th>상태</th>
                <th>관리</th>
              </tr>
            </thead>
            <tbody>
              {reports.length ? reports.map((report) => (
                <tr key={report.id}>
                  <td>{report.report_date}</td>
                  <td>{report.agency}</td>
                  <td>{report.report_type}</td>
                  <td>{report.item_name}</td>
                  <td>{report.variety_name}</td>
                  <td>{report.specification || "-"}</td>
                  <td>{report.quantity.toLocaleString()} {report.unit}</td>
                  <td>{report.customer || "-"}</td>
                  <td><span className={`status ${statusClass(report.status)}`}>{report.status}</span></td>
                  <td>
                    <button className="table-button edit" onClick={() => navigate(`/reports/${report.id}/edit`)}>수정</button>
                    <button className="table-button delete" onClick={() => remove(report.id)}>삭제</button>
                  </td>
                </tr>
              )) : (
                <tr><td colSpan="10" className="empty-cell">등록된 신고가 없습니다.</td></tr>
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
