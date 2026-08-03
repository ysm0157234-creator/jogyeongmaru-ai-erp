import { useState } from "react";
import { ArrowRight, LockKeyhole, Mail, Sparkles } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { api, setToken } from "../services/api";

export default function LoginPage() {
  const navigate = useNavigate();
  const [email, setEmail] = useState("admin@jogyeongmaru.co.kr");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function submit(event) {
    event.preventDefault();
    setLoading(true);
    setError("");

    try {
      const result = await api("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      setToken(result.access_token);
      navigate("/");
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="login-page">
      <div className="login-visual">
        <div className="login-visual-badge">
          <Sparkles size={18} />
          Jogyeongmaru AI ERP
        </div>
        <h2>조경 업무를<br />더 빠르고 간단하게.</h2>
        <p>
          생산·판매 신고부터 자동신고, 재고관리, 수출입까지
          하나의 시스템에서 관리합니다.
        </p>
        <div className="visual-cards">
          <div className="visual-card"><strong>실시간</strong><span>신고 현황</span></div>
          <div className="visual-card"><strong>자동화</strong><span>반복 업무</span></div>
          <div className="visual-card"><strong>통합</strong><span>업무 관리</span></div>
        </div>
      </div>

      <div className="login-card-wrap">
        <div className="login-card">
          <div className="login-logo"><Sparkles size={22} /></div>
          <p className="eyebrow">WELCOME BACK</p>
          <h1>관리자 로그인</h1>
          <p className="muted">조경마루 AI ERP에 접속하세요.</p>

          <form onSubmit={submit} className="login-form">
            <label>
              이메일
              <div className="input-with-icon">
                <Mail size={18} />
                <input
                  type="email"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  required
                />
              </div>
            </label>

            <label>
              비밀번호
              <div className="input-with-icon">
                <LockKeyhole size={18} />
                <input
                  type="password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  required
                  placeholder="비밀번호 입력"
                />
              </div>
            </label>

            {error && <div className="error-box">{error}</div>}

            <button className="primary-button login-button" disabled={loading}>
              {loading ? "로그인 중..." : "로그인"}
              {!loading && <ArrowRight size={18} />}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
