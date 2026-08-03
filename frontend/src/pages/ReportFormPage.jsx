import { useEffect, useMemo, useState } from "react";
import { Check, ChevronLeft, ChevronRight } from "lucide-react";
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

const steps = [
  ["기본정보", "기관과 신고 구분"],
  ["품목정보", "품목과 수량"],
  ["판매정보", "거래처와 비고"],
];

export default function ReportFormPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [form, setForm] = useState(emptyForm);
  const [step, setStep] = useState(0);
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(Boolean(id));
  const [error, setError] = useState("");

  useEffect(() => {
    if (id) {
      api(`/api/reports/${id}`)
        .then((data) => setForm(data))
        .catch((err) => setError(err.message))
        .finally(() => setLoading(false));
    }
  }, [id]);

  const canNext = useMemo(() => {
    if (step === 0) return Boolean(form.report_date && form.agency && form.report_type);
    if (step === 1) return Boolean(form.item_name && form.variety_name && Number(form.quantity) > 0);
    return true;
  }, [form, step]);

  function update(name, value) {
    setForm((current) => ({ ...current, [name]: value }));
  }

  async function submit(event) {
    event.preventDefault();
    setSaving(true);
    setError("");

    try {
      const payload = { ...form, quantity: Number(form.quantity) };
      await api(id ? `/api/reports/${id}` : "/api/reports", {
        method: id ? "PUT" : "POST",
        body: JSON.stringify(payload),
      });
      navigate("/reports");
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return <section className="panel loading-panel">신고 자료를 불러오는 중입니다.</section>;
  }

  return (
    <div>
      <header className="page-header">
        <div>
          <p className="eyebrow">REPORT FORM</p>
          <h1>{id ? "신고 자료 수정" : "생산·판매 신고 등록"}</h1>
          <p className="muted">단계별로 필요한 정보만 입력하세요.</p>
        </div>
      </header>

      {error && <div className="error-banner">{error}</div>}

      <section className="stepper">
        {steps.map(([title, description], index) => (
          <div className={`step ${index === step ? "active" : ""} ${index < step ? "complete" : ""}`} key={title}>
            <div className="step-number">{index < step ? <Check size={16} /> : index + 1}</div>
            <div>
              <strong>{title}</strong>
              <span>{description}</span>
            </div>
          </div>
        ))}
      </section>

      <form className="panel report-form" onSubmit={submit}>
        {step === 0 && (
          <>
            <h2>신고 기본정보</h2>
            <p className="section-description">신고 기관과 기본 처리정보를 입력합니다.</p>
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
          </>
        )}

        {step === 1 && (
          <>
            <h2>품목정보</h2>
            <p className="section-description">품목, 품종, 규격과 수량을 입력합니다.</p>
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
          </>
        )}

        {step === 2 && (
          <>
            <h2>판매정보</h2>
            <p className="section-description">판매처와 추가 메모를 입력합니다.</p>
            <div className="form-grid">
              <Field label="판매처 / 거래처">
                <input value={form.customer} onChange={(e) => update("customer", e.target.value)} />
              </Field>
              <Field label="거래처 주소" wide>
                <input value={form.customer_address} onChange={(e) => update("customer_address", e.target.value)} />
              </Field>
              <Field label="비고" full>
                <textarea rows="5" value={form.memo} onChange={(e) => update("memo", e.target.value)} />
              </Field>
            </div>
          </>
        )}

        <div className="form-actions spread">
          <div>
            <button type="button" className="secondary-button icon-button" onClick={() => step === 0 ? navigate("/reports") : setStep(step - 1)}>
              <ChevronLeft size={18} />
              {step === 0 ? "취소" : "이전"}
            </button>
          </div>

          <div>
            {step < 2 ? (
              <button type="button" className="primary-button icon-button" disabled={!canNext} onClick={() => setStep(step + 1)}>
                다음
                <ChevronRight size={18} />
              </button>
            ) : (
              <button className="primary-button" disabled={saving}>
                {saving ? "저장 중..." : "저장"}
              </button>
            )}
          </div>
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
