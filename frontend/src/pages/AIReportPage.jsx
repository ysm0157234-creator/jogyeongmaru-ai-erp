import React, { useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  ExternalLink,
  FileSearch,
  Image as ImageIcon,
  LoaderCircle,
  Search,
  Sparkles,
} from "lucide-react";
import { api, apiDownload } from "../services/api";

export default function AIReportPage() {
  const [varietyName, setVarietyName] = useState("Tulipa spp. Sunlover");
  const [agency, setAgency] = useState("국립종자원");
  const [loading, setLoading] = useState(false);
  const [draft, setDraft] = useState(null);
  const [error, setError] = useState("");
  const [selectedImages, setSelectedImages] = useState(["commons-01", "commons-02"]);
  const [driveStatus, setDriveStatus] = useState(null);
  const [fileLoading, setFileLoading] = useState(false);

  async function loadDriveStatus() {
    try {
      setDriveStatus(await api("/api/ai-reports/drive/status"));
    } catch {
      setDriveStatus(null);
    }
  }

  async function generateFiles() {
    setFileLoading(true);
    setError("");
    try {
      const response = await apiDownload("/api/ai-reports/generate-files", {
        method: "POST",
        body: JSON.stringify({ variety_name: varietyName, agency }),
      });
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = "Tulipa_Sunlover_생산판매신고_자동생성.zip";
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err.message);
    } finally {
      setFileLoading(false);
    }
  }

  async function generate(event) {
    event.preventDefault();
    setLoading(true);
    setError("");
    setDraft(null);

    try {
      const result = await api("/api/ai-reports/generate", {
        method: "POST",
        body: JSON.stringify({
          variety_name: varietyName,
          agency,
        }),
      });
      setDraft(result);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  function toggleImage(id) {
    setSelectedImages((current) =>
      current.includes(id) ? current.filter((value) => value !== id) : [...current, id]
    );
  }

  React.useEffect(() => { loadDriveStatus(); }, []);

  return (
    <div>
      <header className="page-header">
        <div>
          <p className="eyebrow">AI REPORT BUILDER</p>
          <h1>AI 생산·판매 신고 생성</h1>
          <p className="muted">
            품종명만 입력하면 Drive 자료와 웹 정보를 모아 신고 초안을 만듭니다.
          </p>
        </div>
      </header>

      <section className="ai-hero panel">
        <div className="ai-hero-icon"><Sparkles size={26} /></div>
        <div>
          <h2>품종 하나만 입력하세요</h2>
          <p>현재 시험 품종: Tulipa spp. Sunlover</p>
        </div>
      </section>

      <section className={`panel drive-status ${driveStatus?.configured ? "connected" : "disconnected"}`}>
        <div>
          <strong>Google Drive 연결</strong>
          <span>{driveStatus?.message || "연결상태 확인 중..."}</span>
        </div>
        <small>Shipment Overview → Shipment 번호 → 2026 수입 폴더 → Invoice 자동가공</small>
      </section>

      <form className="panel ai-search-form" onSubmit={generate}>
        <label className="field">
          <span>신고할 품종명</span>
          <div className="search-box large">
            <Search size={20} />
            <input
              value={varietyName}
              onChange={(event) => setVarietyName(event.target.value)}
              placeholder="예: Tulipa spp. Sunlover"
              required
            />
          </div>
        </label>

        <label className="field">
          <span>신고 기관</span>
          <select value={agency} onChange={(event) => setAgency(event.target.value)}>
            <option>국립종자원</option>
            <option>산림청</option>
            <option>둘 다</option>
          </select>
        </label>

        <button className="primary-button ai-generate-button" disabled={loading}>
          {loading ? <LoaderCircle size={19} className="spin" /> : <Sparkles size={19} />}
          {loading ? "자료를 찾는 중..." : "AI 신고자료 생성"}
        </button>
      </form>

      {error && <div className="error-banner">{error}</div>}

      {draft && (
        <>
          <AIResult draft={draft} selectedImages={selectedImages} toggleImage={toggleImage} />
          <section className="panel actual-file-box">
            <div>
              <h2>실제 신고파일 만들기</h2>
              <p>
                Shipment Overview에서 컨테이너 번호를 찾고, 2026 수입 폴더의
                인보이스를 찾아 신고용 파일로 가공합니다.
              </p>
            </div>
            <button
              className="primary-button icon-button"
              disabled={fileLoading || !driveStatus?.configured}
              onClick={generateFiles}
            >
              {fileLoading ? <LoaderCircle size={18} className="spin" /> : <FileSearch size={18} />}
              {fileLoading ? "파일 생성 중..." : "신고서·인보이스 ZIP 생성"}
            </button>
            {!driveStatus?.configured && (
              <div className="warning-box">
                Render API Environment에 GOOGLE_SERVICE_ACCOUNT_JSON을 먼저 등록하세요.
              </div>
            )}
          </section>
        </>
      )}
    </div>
  );
}

function AIResult({ draft, selectedImages, toggleImage }) {
  const data = draft.result_data;

  return (
    <div className="ai-result">
      <section className="panel ai-result-header">
        <div>
          <p className="eyebrow">AI DRAFT #{draft.id}</p>
          <h2>{data.matched_name}</h2>
          <p className="muted">{data.korean_name} · 일치도 {data.match_confidence}%</p>
        </div>
        <span className="status pending">{draft.status}</span>
      </section>

      <section className="ai-summary-grid">
        <SummaryCard label="학명" value={data.scientific_name} />
        <SummaryCard label="원예 분류" value={data.classification.horticultural_group} />
        <SummaryCard label="꽃 색상" value={data.classification.flower_color} />
        <SummaryCard label="개화기" value={data.classification.flowering_period} />
        <SummaryCard label="초장" value={data.classification.height} />
        <SummaryCard label="신고 기관" value={data.requested_agency} />
      </section>

      <section className="panel">
        <SectionTitle icon={FileSearch} title="Drive 자료 검색 결과" />
        <div className="source-list">
          {data.drive_sources.map((source) => <SourceRow key={source.url} source={source} />)}
          {data.shipment_match.candidate_files.map((source) => (
            <SourceRow key={source.url} source={{ ...source, type: source.purpose, status: "후보" }} />
          ))}
        </div>
        <div className="warning-box">
          <AlertTriangle size={18} />
          <span>{data.shipment_match.message}</span>
        </div>
      </section>

      <section className="panel">
        <SectionTitle icon={Sparkles} title="AI 작성 초안" />
        <div className="draft-text-grid">
          <article>
            <h3>품종의 특성 설명</h3>
            <textarea defaultValue={data.characteristics_draft} rows="7" />
          </article>
          <article>
            <h3>품종의 육성과정</h3>
            <textarea defaultValue={data.breeding_process_draft} rows="7" />
          </article>
        </div>
      </section>

      <section className="panel">
        <SectionTitle icon={ImageIcon} title="웹 사진 후보" />
        <p className="muted ai-section-note">
          추천 사진이 기본 선택돼 있습니다. 품종이 맞는지 확인한 뒤 사용하세요.
        </p>
        <div className="image-candidate-grid">
          {data.image_candidates.map((image) => {
            const selected = selectedImages.includes(image.id);
            return (
              <button
                type="button"
                className={`image-candidate ${selected ? "selected" : ""}`}
                key={image.id}
                onClick={() => toggleImage(image.id)}
              >
                <img src={image.preview_url} alt={image.title} />
                <div className="image-candidate-body">
                  <strong>{image.title}</strong>
                  <span>{image.source}</span>
                  <small>{image.license}</small>
                  <div className="image-selected-label">
                    {selected ? <CheckCircle2 size={16} /> : null}
                    {selected ? "선택됨" : "선택"}
                  </div>
                </div>
              </button>
            );
          })}
        </div>
      </section>

      <section className="panel">
        <SectionTitle icon={FileSearch} title="필요 서류 체크" />
        <div className="document-check-grid">
          {data.required_documents.map((item) => (
            <div className="document-check" key={item.name}>
              <CheckCircle2 size={18} />
              <div><strong>{item.name}</strong><span>{item.status}</span></div>
            </div>
          ))}
        </div>
      </section>

      <section className="panel">
        <SectionTitle icon={ExternalLink} title="웹 조사 출처" />
        <div className="source-list">
          {data.web_sources.map((source) => <SourceRow key={source.url} source={source} />)}
        </div>
      </section>

      <section className="panel warning-panel">
        <SectionTitle icon={AlertTriangle} title="최종 확인 필요" />
        {data.warnings.map((warning) => (
          <div className="warning-line" key={warning}><AlertTriangle size={17} />{warning}</div>
        ))}
        <div className="ai-final-actions">
          <button className="secondary-button">초안 수정</button>
          <button
            className="primary-button"
            onClick={() => window.alert("검토함 저장 완료. 다음 버전에서 정부 사이트 자동입력 단계와 연결합니다.")}
          >
            신고 검토함에 저장
          </button>
        </div>
      </section>
    </div>
  );
}

function SummaryCard({ label, value }) {
  return <article className="ai-summary-card"><span>{label}</span><strong>{value}</strong></article>;
}

function SectionTitle({ icon: Icon, title }) {
  return <div className="ai-section-title"><Icon size={20} /><h2>{title}</h2></div>;
}

function SourceRow({ source }) {
  return (
    <a className="source-row" href={source.url} target="_blank" rel="noreferrer">
      <div>
        <strong>{source.title}</strong>
        <span>{source.type}</span>
      </div>
      <div className="source-row-right">
        <span className="source-status">{source.status}</span>
        <ExternalLink size={16} />
      </div>
    </a>
  );
}
