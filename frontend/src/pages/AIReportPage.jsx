import React, { useEffect, useMemo, useState } from "react";
import {
  CheckCircle2,
  FileSearch,
  Image as ImageIcon,
  LoaderCircle,
  Pencil,
  Save,
  Search,
  Sparkles,
  X,
} from "lucide-react";

import { api, apiDownload } from "../services/api";

export default function AIReportPage() {
  const [varietyName, setVarietyName] = useState("Tulipa spp. Sunlover");
  const [agency, setAgency] = useState("국립종자원");

  const [draft, setDraft] = useState(null);
  const [loading, setLoading] = useState(false);

  const [driveStatus, setDriveStatus] = useState(null);
  const [driveStatusLoading, setDriveStatusLoading] = useState(true);

  const [error, setError] = useState("");
  const [fileLoading, setFileLoading] = useState(false);
  const [fileStatus, setFileStatus] = useState("");

  useEffect(() => {
    loadDriveStatus();
  }, []);

  async function loadDriveStatus() {
    setDriveStatusLoading(true);

    try {
      const result = await api("/api/ai-reports/drive/status");
      setDriveStatus(result);
    } catch (err) {
      console.error("Drive status error:", err);
      setDriveStatus(null);
    } finally {
      setDriveStatusLoading(false);
    }
  }

  async function generate(event) {
    event.preventDefault();

    setLoading(true);
    setError("");
    setFileStatus("");
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

  async function generateFiles() {
    if (!draft) {
      setError("먼저 AI 신고자료를 생성하세요.");
      return;
    }

    setFileLoading(true);
    setError("");
    setFileStatus(
      "Google Drive에서 인보이스, 검역합격증, 사진 자료를 확인하고 있습니다."
    );

    try {
      const response = await apiDownload(
        "/api/ai-reports/generate-files",
        {
          method: "POST",
          body: JSON.stringify({
            variety_name: varietyName,
            agency,
            draft_id: draft.id,
          }),
        }
      );

      const blob = await response.blob();

      if (!blob.size) {
        throw new Error("서버가 빈 ZIP 파일을 반환했습니다.");
      }

      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");

      link.href = url;
      link.download = "Tulipa_Sunlover_complete.zip";

      document.body.appendChild(link);
      link.click();
      link.remove();

      setTimeout(() => {
        URL.revokeObjectURL(url);
      }, 1000);

      setFileStatus("완료: ZIP 다운로드를 시작했습니다.");
    } catch (err) {
      const message =
        err?.message || "ZIP 생성 중 알 수 없는 오류가 발생했습니다.";

      setError(message);
      setFileStatus(`실패: ${message}`);
    } finally {
      setFileLoading(false);
    }
  }

  return (
    <div>
      <header className="page-header">
        <div>
          <p className="eyebrow">AI REPORT BUILDER</p>
          <h1>AI 생산·판매 신고 생성</h1>
        </div>
      </header>

      <section
        className={`panel drive-status ${
          driveStatus?.configured ? "connected" : "disconnected"
        }`}
      >
        <div>
          <strong>Google Drive 연결</strong>

          <span>
            {driveStatusLoading
              ? "연결상태 확인 중..."
              : driveStatus === null
              ? "연결상태를 확인하지 못했습니다. ZIP 생성을 눌러 실제 오류를 확인하세요."
              : driveStatus.message}
          </span>
        </div>

        <button
          type="button"
          className="secondary-button"
          onClick={loadDriveStatus}
          disabled={driveStatusLoading}
        >
          {driveStatusLoading ? "확인 중..." : "연결상태 다시 확인"}
        </button>
      </section>

      <form className="panel ai-search-form" onSubmit={generate}>
        <label className="field">
          <span>신고할 품종명</span>

          <div className="search-box large">
            <Search size={20} />

            <input
              value={varietyName}
              onChange={(event) =>
                setVarietyName(event.target.value)
              }
              placeholder="예: Tulipa spp. Sunlover"
              required
            />
          </div>
        </label>

        <label className="field">
          <span>신고 기관</span>

          <select
            value={agency}
            onChange={(event) =>
              setAgency(event.target.value)
            }
          >
            <option>국립종자원</option>
            <option>산림청</option>
            <option>둘 다</option>
          </select>
        </label>

        <button
          className="primary-button ai-generate-button"
          disabled={loading}
        >
          {loading ? (
            <LoaderCircle
              className="spin"
              size={19}
            />
          ) : (
            <Sparkles size={19} />
          )}

          {loading
            ? "자료를 찾는 중..."
            : "AI 신고자료 생성"}
        </button>
      </form>

      {error && (
        <div className="error-banner">
          {error}
        </div>
      )}

      {draft && (
        <>
          <AIResult
            draft={draft}
            setDraft={setDraft}
            setError={setError}
          />

          <section className="panel actual-file-box">
            <div>
              <h2>실제 신고파일 만들기</h2>

              <p>
                저장한 초안과 전체 모습 사진,
                꽃 근접 사진을 문서에 반영합니다.
              </p>
            </div>

            <button
              type="button"
              className="primary-button icon-button"
              onClick={generateFiles}
              disabled={fileLoading}
            >
              {fileLoading ? (
                <LoaderCircle
                  className="spin"
                  size={18}
                />
              ) : (
                <FileSearch size={18} />
              )}

              {fileLoading
                ? "ZIP 생성 중..."
                : "ZIP 생성"}
            </button>

            {fileStatus && (
              <div
                className={`file-status-message ${
                  fileStatus.startsWith("실패")
                    ? "failed"
                    : fileStatus.startsWith("완료")
                    ? "success"
                    : "working"
                }`}
              >
                {fileLoading && (
                  <LoaderCircle
                    className="spin"
                    size={17}
                  />
                )}

                <span>{fileStatus}</span>
              </div>
            )}
          </section>
        </>
      )}
    </div>
  );
}

function AIResult({
  draft,
  setDraft,
  setError,
}) {
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);

  const [form, setForm] = useState(() =>
    structuredClone(draft.result_data)
  );

  useEffect(() => {
    setForm(
      structuredClone(draft.result_data)
    );
  }, [draft]);

  const overallImages = useMemo(() => {
    return (form.image_candidates || []).filter(
      (image) => image.role === "overall"
    );
  }, [form.image_candidates]);

  const closeupImages = useMemo(() => {
    return (form.image_candidates || []).filter(
      (image) => image.role === "closeup"
    );
  }, [form.image_candidates]);

  function change(path, value) {
    setForm((current) => {
      const next = structuredClone(current);

      let target = next;

      for (
        let index = 0;
        index < path.length - 1;
        index += 1
      ) {
        target = target[path[index]];
      }

      target[path[path.length - 1]] = value;

      return next;
    });
  }

  function selectImage(role, id) {
    setForm((current) => ({
      ...current,
      selected_images: {
        ...(current.selected_images || {}),
        [role]: id,
      },
    }));
  }

  async function save() {
    setSaving(true);
    setError("");

    try {
      const selected =
        form.selected_images || {};

      if (
        !selected.overall ||
        !selected.closeup
      ) {
        throw new Error(
          "전체 모습 사진과 꽃 근접 사진을 각각 선택하세요."
        );
      }

      if (
        selected.overall ===
        selected.closeup
      ) {
        throw new Error(
          "전체 모습과 꽃 근접 사진은 서로 달라야 합니다."
        );
      }

      const updated = await api(
        `/api/ai-reports/${draft.id}`,
        {
          method: "PUT",
          body: JSON.stringify({
            result_data: form,
            status: "검토 완료",
          }),
        }
      );

      setDraft(updated);
      setEditing(false);
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  function cancelEdit() {
    setForm(
      structuredClone(draft.result_data)
    );
    setEditing(false);
  }

  return (
    <div className="ai-result">
      <section className="panel ai-result-header">
        <div>
          <p className="eyebrow">
            AI DRAFT #{draft.id}
          </p>

          {editing ? (
            <div className="edit-title-grid">
              <input
                value={form.matched_name}
                onChange={(event) =>
                  change(
                    ["matched_name"],
                    event.target.value
                  )
                }
              />

              <input
                value={form.korean_name}
                onChange={(event) =>
                  change(
                    ["korean_name"],
                    event.target.value
                  )
                }
              />
            </div>
          ) : (
            <>
              <h2>{form.matched_name}</h2>

              <p className="muted">
                {form.korean_name}
              </p>
            </>
          )}
        </div>

        <span className="status pending">
          {draft.status}
        </span>
      </section>

      <section className="ai-summary-grid">
        <Card
          editing={editing}
          label="학명"
          value={form.scientific_name}
          onChange={(value) =>
            change(
              ["scientific_name"],
              value
            )
          }
        />

        <Card
          editing={editing}
          label="꽃 색상"
          value={
            form.classification.flower_color
          }
          onChange={(value) =>
            change(
              [
                "classification",
                "flower_color",
              ],
              value
            )
          }
        />

        <Card
          editing={editing}
          label="개화기"
          value={
            form.classification
              .flowering_period
          }
          onChange={(value) =>
            change(
              [
                "classification",
                "flowering_period",
              ],
              value
            )
          }
        />

        <Card
          editing={editing}
          label="초장"
          value={
            form.classification.height
          }
          onChange={(value) =>
            change(
              [
                "classification",
                "height",
              ],
              value
            )
          }
        />
      </section>

      <section className="panel">
        <h2>AI 작성 초안</h2>

        <div className="draft-text-grid">
          <article>
            <h3>품종의 특성 설명</h3>

            <textarea
              rows="7"
              disabled={!editing}
              value={
                form.characteristics_draft
              }
              onChange={(event) =>
                change(
                  [
                    "characteristics_draft",
                  ],
                  event.target.value
                )
              }
            />
          </article>

          <article>
            <h3>품종의 육성과정</h3>

            <textarea
              rows="7"
              disabled={!editing}
              value={
                form.breeding_process_draft
              }
              onChange={(event) =>
                change(
                  [
                    "breeding_process_draft",
                  ],
                  event.target.value
                )
              }
            />
          </article>
        </div>
      </section>

      <Photo
        title="사진 1 · 품종 전체 모습"
        description="식물 또는 꽃대 전체 형태가 보이는 사진"
        images={overallImages}
        selected={
          form.selected_images?.overall
        }
        onSelect={(id) =>
          selectImage("overall", id)
        }
      />

      <Photo
        title="사진 2 · 꽃 근접 모습"
        description="꽃잎 색상과 형태가 잘 보이는 근접 사진"
        images={closeupImages}
        selected={
          form.selected_images?.closeup
        }
        onSelect={(id) =>
          selectImage("closeup", id)
        }
      />

      <section className="panel warning-panel">
        <div className="ai-final-actions">
          {!editing ? (
            <button
              type="button"
              className="secondary-button icon-button"
              onClick={() =>
                setEditing(true)
              }
            >
              <Pencil size={17} />
              초안 수정
            </button>
          ) : (
            <>
              <button
                type="button"
                className="secondary-button icon-button"
                onClick={cancelEdit}
              >
                <X size={17} />
                취소
              </button>

              <button
                type="button"
                className="primary-button icon-button"
                onClick={save}
                disabled={saving}
              >
                {saving ? (
                  <LoaderCircle
                    className="spin"
                    size={17}
                  />
                ) : (
                  <Save size={17} />
                )}

                {saving
                  ? "저장 중..."
                  : "수정 저장"}
              </button>
            </>
          )}

          {!editing && (
            <button
              type="button"
              className="primary-button"
              onClick={save}
              disabled={saving}
            >
              {saving
                ? "저장 중..."
                : "신고 검토함에 저장"}
            </button>
          )}
        </div>
      </section>
    </div>
  );
}

function Card({
  editing,
  label,
  value,
  onChange,
}) {
  return (
    <article className="ai-summary-card">
      <span>{label}</span>

      {editing ? (
        <input
          value={value}
          onChange={(event) =>
            onChange(event.target.value)
          }
        />
      ) : (
        <strong>{value}</strong>
      )}
    </article>
  );
}

function Photo({
  title,
  description,
  images,
  selected,
  onSelect,
}) {
  return (
    <section className="panel">
      <div className="ai-section-title">
        <ImageIcon size={20} />
        <h2>{title}</h2>
      </div>

      <p className="muted">
        {description}
      </p>

      {images.length === 0 ? (
        <div className="warning-box">
          이 역할에 맞는 사진 후보가 없습니다.
        </div>
      ) : (
        <div className="image-candidate-grid">
          {images.map((image) => (
            <button
              type="button"
              key={image.id}
              className={`image-candidate ${
                selected === image.id
                  ? "selected"
                  : ""
              }`}
              onClick={() =>
                onSelect(image.id)
              }
            >
              <img
                src={image.preview_url}
                alt={image.title}
              />

              <div className="image-candidate-body">
                <strong>
                  {image.title}
                </strong>

                <span>
                  {image.source}
                </span>

                <div className="image-selected-label">
                  {selected === image.id && (
                    <CheckCircle2 size={16} />
                  )}

                  {selected === image.id
                    ? "이 사진 사용"
                    : "선택"}
                </div>
              </div>
            </button>
          ))}
        </div>
      )}
    </section>
  );
}
