import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../services/api";

const emptyForm = {
  agency: "국립종자원",
  report_type: "생산 신고",
  report_date: new Date().toISOString().slice(0, 10),
  status: "작성 중",
  item_name: "",
  variety_name: "",
  specification: "",
  quantity: "",
  unit: "주",
  production_location: "",
  lot_no: "",
  customer: "",
  customer_address: "",
  manager: "",
  memo: "",
};

export default function ReportFormPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [form, setForm] = useState(emptyForm);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (id) {
      api(`/api/reports/${id}`).then((data) => setForm(data));
    }
  }, [id]);

  function update(name, value) {
    setForm((current) => ({ ...current, [name]: value }));
  }

  async function submit(event) {
    event.preventDefault();
    setSaving(true);

    try {
      const payload = {
        ...form,
        quantity: Number(form.quantity),
      };
      await api(id ? `/api/reports/${id}` : "/api/reports", {
        method: id ? "PUT" : "POST",
        body: JSON.stringify(payload),
      });
      navigate("/reports");
    } catch (error) {
      window.alert(error.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div>
      <header className="page-header">
        <div>
          <p className="eyebrow">REPORT FORM</p>
          <h1>{id ? "신고 자료 수정" : "생산·판매 신고 등록"}</h1>
          <p className="muted">필수 항목을 입력하고 저장하세요.</p>
        </div>
      </header>

      <form className="panel report-form" onSubmit={submit}>
        <h2>신고 기본정보</h2>
        <div className="form-grid">
          <Field label="신고 기관">
            <select value={form.agency} onChange={(e) => update("agency", e.target.value)}>
              <option>국립종자원</option>
              <option>산림청</option>
            </select>
          </Field>
          <Field label="신고 구분">
            <select value={form.report_type} onChange={(e) => update("report_type", e.target.value)}>
              <option>생산 신고</option>
              <option>판매 신고</option>
            </select>
          </Field>
          <Field label="신고일">
            <input type="date" value={form.report_date} onChange={(e) => update("report_date", e.target.value)} required />
          </Field>
          <Field label="처리 상태">
            <select value={form.status} onChange={(e) => update("status", e.target.value)}>
              <option>작성 중</option>
              <option>전송 대기</option>
              <option>완료</option>
            </select>
          </Field>
          <Field label="담당자">
            <input value={form.manager} onChange={(e) => update("manager", e.target.value)} />
          </Field>
          <Field label="로트번호">
            <input value={form.lot_no} onChange={(e) => update("lot_no", e.target.value)} />
          </Field>
        </div>

        <h2>품목정보</h2>
        <div className="form-grid">
          <Field label="품목명">
            <input value={form.item_name} onChange={(e) => update("item_name", e.target.value)} required />
          </Field>
          <Field label="품종명">
            <input value={form.variety_name} onChange={(e) => update("variety_name", e.target.value)} required />
          </Field>
          <Field label="규격">
            <input value={form.specification} onChange={(e) => update("specification", e.target.value)} placeholder="예: P9, H1.5" />
          </Field>
          <Field label="수량">
            <input type="number" min="1" value={form.quantity} onChange={(e) => update("quantity", e.target.value)} required />
          </Field>
          <Field label="단위">
            <select value={form.unit} onChange={(e) => update("unit", e.target.value)}>
              <option>주</option><option>본</option><option>개</option><option>kg</option><option>봉</option>
            </select>
          </Field>
          <Field label="생산지 / 보관지">
            <input value={form.production_location} onChange={(e) => update("production_location", e.target.value)} />
          </Field>
        </div>

        <h2>판매정보</h2>
        <div className="form-grid">
          <Field label="판매처 / 거래처">
            <input value={form.customer} onChange={(e) => update("customer", e.target.value)} />
          </Field>
          <Field label="거래처 주소" wide>
            <input value={form.customer_address} onChange={(e) => update("customer_address", e.target.value)} />
          </Field>
          <Field label="비고" full>
            <textarea rows="4" value={form.memo} onChange={(e) => update("memo", e.target.value)} />
          </Field>
        </div>

        <div className="form-actions">
          <button type="button" className="secondary-button" onClick={() => navigate("/reports")}>취소</button>
          <button className="primary-button" disabled={saving}>{saving ? "저장 중..." : "저장"}</button>
        </div>
      </form>
    </div>
  );
}

function Field({ label, children, wide, full }) {
  return (
    <label className={`field ${wide ? "wide" : ""} ${full ? "full" : ""}`}>
      <span>{label}</span>
      {children}
    </label>
  );
}
