import React, { useEffect, useMemo, useState } from "react";
import { AlertTriangle, CheckCircle2, FileSearch, Image as ImageIcon, LoaderCircle, Pencil, Save, Search, Sparkles, X } from "lucide-react";
import { API_URL, api, apiDownload, apiUpload } from "../services/api";

// 맥에서 도는 신고 도우미. 브라우저 로그인 세션이 있는 컴퓨터에서만 동작한다.
const HELPER_URL = "http://127.0.0.1:8765";

export default function AIReportPage() {
  const [varietyName, setVarietyName] = useState("");
  const [agency, setAgency] = useState("국립종자원");
  const [draft, setDraft] = useState(null);
  const [loading, setLoading] = useState(false);
  const [driveStatus, setDriveStatus] = useState(null);
  const [error, setError] = useState("");
  const [fileLoading, setFileLoading] = useState(false);
  const [seednetLoading, setSeednetLoading] = useState(false);
  const [seednetStatus, setSeednetStatus] = useState("");
  const [seednetResult, setSeednetResult] = useState(null);
  const [fileStatus, setFileStatus] = useState("");
  const [researchStatus, setResearchStatus] = useState("");
  const [currentResultData, setCurrentResultData] = useState(null);

  useEffect(() => {
    api("/api/ai-reports/drive/status").then(setDriveStatus).catch(() => setDriveStatus(null));
  }, []);

  async function generate(event) {
    event.preventDefault();
    const requestedName = varietyName.trim();
    setDraft(null);
    setCurrentResultData(null);
    setLoading(true);
    setError("");
    setFileStatus("");

    try {
      const response = await api("/api/ai-reports/generate", {
        method: "POST",
        body: JSON.stringify({ variety_name: requestedName, agency }),
      });

      setResearchStatus("인터넷 자료 검색과 AI 번역·요약을 진행하고 있습니다.");
      const completed = await waitForDraft(response.id, requestedName, setResearchStatus);
      setDraft(completed);
      setCurrentResultData(completed.result_data);
      setResearchStatus("");
    } catch (err) {
      setDraft(null);
      setResearchStatus("");
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function generateFiles() {
    setFileLoading(true); setError(""); setFileStatus("신고서와 사진 파일을 만들고 있습니다.");
    try {
      if (currentResultData) {
        const updated = await api(`/api/ai-reports/${draft.id}`, {
          method: "PUT",
          body: JSON.stringify({ result_data: currentResultData, status: "검토 완료" }),
        });
        setDraft(updated);
      }
      const response = await apiDownload("/api/ai-reports/generate-files", {
        method: "POST",
        body: JSON.stringify({ variety_name: varietyName, agency, draft_id: draft.id }),
      });
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url; link.download = `${varietyName.replace(/[^a-zA-Z0-9가-힣_-]+/g, "_") || "plant"}_complete.zip`;
      document.body.appendChild(link); link.click(); link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      setFileStatus("완료: ZIP 다운로드를 시작했습니다.");
    } catch (err) {
      setError(err.message); setFileStatus(`실패: ${err.message}`);
    } finally { setFileLoading(false); }
  }

  // 국립종자원 신고는 로그인된 브라우저가 있는 이 컴퓨터에서 돌아야 한다.
  // Render 서버는 그 세션을 가질 수 없으므로, 맥에서 도는 도우미(127.0.0.1:8765)에 ZIP을 넘긴다.
  async function fileToSeednet() {
    setSeednetLoading(true); setError(""); setSeednetResult(null);
    setSeednetStatus("도우미 프로그램을 확인하고 있습니다.");
    try {
      try {
        const health = await fetch(`${HELPER_URL}/health`, { signal: AbortSignal.timeout(3000) });
        if (!health.ok) throw new Error();
      } catch {
        throw new Error(
          "도우미에 연결하지 못했습니다.\n" +
          "1) Safari에서는 동작하지 않습니다. Chrome으로 열어 주세요.\n" +
          "2) 도우미가 꺼져 있다면 터미널에서 실행하세요:\n" +
          "   cd ~/Documents/GitHub/jogyeongmaru-ai-erp/automation && python3 -m seednet.local_server"
        );
      }

      if (currentResultData) {
        const updated = await api(`/api/ai-reports/${draft.id}`, {
          method: "PUT",
          body: JSON.stringify({ result_data: currentResultData, status: "검토 완료" }),
        });
        setDraft(updated);
      }

      setSeednetStatus("신고 자료를 만들고 있습니다.");
      const response = await apiDownload("/api/ai-reports/generate-files", {
        method: "POST",
        body: JSON.stringify({ variety_name: varietyName, agency, draft_id: draft.id }),
      });
      const blob = await response.blob();

      setSeednetStatus("국립종자원 화면을 채우고 있습니다. 맥에 열린 브라우저를 확인하세요.");
      const form = new FormData();
      form.append("file", blob, "package.zip");
      const run = await fetch(`${HELPER_URL}/run`, { method: "POST", body: form });
      const result = await run.json();
      if (!run.ok) throw new Error(result.error || "신고 자동입력에 실패했습니다.");

      setSeednetResult(result);
      setSeednetStatus("완료: 열린 브라우저에서 확인 후 [종자원 접수요청]을 눌러 주세요.");
    } catch (err) {
      setError(err.message); setSeednetStatus(`실패: ${err.message}`);
    } finally { setSeednetLoading(false); }
  }

  return <div>
    <header className="page-header"><div><p className="eyebrow">AI REPORT BUILDER</p><h1>AI 생산·판매 신고 생성</h1></div></header>
    <section className={`panel drive-status ${driveStatus?.configured ? "connected" : "disconnected"}`}>
      <div><strong>Google Drive 연결</strong><span>{driveStatus?.message || "확인 중..."}</span></div>
    </section>
    <form className="panel ai-search-form" onSubmit={generate}>
      <label className="field"><span>신고할 품종명</span><div className="search-box large"><Search size={20}/><input value={varietyName} onChange={e=>setVarietyName(e.target.value)} placeholder="예: Hydrangea macrophylla Endless Summer" required /></div></label>
      <label className="field"><span>신고 기관</span><select value={agency} onChange={e=>setAgency(e.target.value)}><option>국립종자원</option><option>산림청</option><option>둘 다</option></select></label>
      <button className="primary-button ai-generate-button" disabled={loading}>{loading?<LoaderCircle className="spin" size={19}/>:<Sparkles size={19}/>} AI 신고자료 생성</button>
    </form>
    {researchStatus && <div className="file-status-message working"><LoaderCircle className="spin" size={18}/>{researchStatus}</div>}
    {error && <div className="error-banner">{error}</div>}
    {draft && <>
      <AIResult draft={draft} setDraft={setDraft} setError={setError} onFormChange={setCurrentResultData}/>
      <section className="panel actual-file-box">
        <div><h2>실제 신고파일 만들기</h2><p>저장한 초안과 전체샷·근접샷을 문서에 반영합니다.</p></div>
        <button className="primary-button icon-button" onClick={generateFiles} disabled={fileLoading || !driveStatus?.configured}>{fileLoading?<LoaderCircle className="spin" size={18}/>:<FileSearch size={18}/>} ZIP 생성</button>
        {fileStatus && <div className={`file-status-message ${fileStatus.startsWith("실패")?"failed":fileStatus.startsWith("완료")?"success":"working"}`}>{fileStatus}</div>}
      </section>
      <section className="panel actual-file-box">
        <div>
          <h2>국립종자원 신고 자동입력</h2>
          <p>seednet 신고 화면을 자동으로 채웁니다. 제출 버튼은 직접 누르셔야 합니다.</p>
        </div>
        <button className="primary-button icon-button" onClick={fileToSeednet} disabled={seednetLoading || !driveStatus?.configured}>{seednetLoading?<LoaderCircle className="spin" size={18}/>:<FileSearch size={18}/>} 신고 자동입력</button>
        {seednetStatus && <div className={`file-status-message ${seednetStatus.startsWith("실패")?"failed":seednetStatus.startsWith("완료")?"success":"working"}`} style={{whiteSpace:"pre-line"}}>{seednetStatus}</div>}
        {seednetResult && <div className="seednet-result">
          {seednetResult.saved_to && <p className="muted">신고 자료 보관: {seednetResult.saved_to}</p>}
          <p><strong>자동 처리 {seednetResult.done.length}건</strong></p>
          <ul>{seednetResult.done.map((line,i)=><li key={i}>{line}</li>)}</ul>
          <p><strong>직접 처리할 항목 {seednetResult.todo.length}건</strong></p>
          <ul>{seednetResult.todo.map((line,i)=><li key={i}>{line}</li>)}</ul>
        </div>}
      </section>
    </>}
  </div>;
}


async function waitForDraft(draftId, requestedName, onProgress) {
  const startedAt = Date.now();
  const timeoutMs = 8 * 60 * 1000;

  while (Date.now() - startedAt < timeoutMs) {
    await new Promise(resolve => setTimeout(resolve, 2000));
    const current = await api(`/api/ai-reports/${draftId}`);

    if (current.status === "생성 실패") {
      throw new Error(current?.result_data?.error || "AI 신고자료 생성에 실패했습니다.");
    }

    if (current.status === "검토 대기" || current.status === "검토 완료") {
      const returnedQuery = String(current?.result_data?.research_query || "").trim();
      if (!returnedQuery || returnedQuery.toLowerCase() !== requestedName.toLowerCase()) {
        throw new Error(`서버가 다른 품종 결과를 반환했습니다. 요청: ${requestedName}, 결과: ${returnedQuery || "확인 불가"}`);
      }
      return current;
    }

    onProgress(current?.result_data?.progress || `AI 조사 진행 중 · ${current.status}`);
  }

  throw new Error("조사 시간이 8분을 초과했습니다. 잠시 후 다시 시도하거나 초안 목록에서 상태를 확인하세요.");
}

function AIResult({ draft, setDraft, setError, onFormChange }) {
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState(() => structuredClone(draft.result_data));
  useEffect(()=>setForm(structuredClone(draft.result_data)),[draft]);
  useEffect(()=>onFormChange?.(form),[form,onFormChange]);

  const overall = useMemo(()=>(form.image_candidates || []).filter(i=>i.role==="overall"),[form.image_candidates]);
  const closeup = useMemo(()=>(form.image_candidates || []).filter(i=>i.role==="closeup"),[form.image_candidates]);

  function change(path,value){setForm(current=>{const next=structuredClone(current);let t=next;for(let i=0;i<path.length-1;i++)t=t[path[i]];t[path.at(-1)]=value;return next;});}
  function select(role,id){setForm(c=>({...c,selected_images:{...(c.selected_images||{}),[role]:id}}));}

  async function save(){
    setSaving(true);setError("");
    try{
      const updated=await api(`/api/ai-reports/${draft.id}`,{method:"PUT",body:JSON.stringify({result_data:form,status:"검토 완료"})});
      setDraft(updated);setEditing(false);
    }catch(err){setError(err.message);}finally{setSaving(false);}
  }

  return <div className="ai-result">
    <section className="panel ai-result-header"><div><p className="eyebrow">AI DRAFT #{draft.id} · {form.build_version || "버전 확인 불가"}</p>{editing?<div className="edit-title-grid"><input value={form.matched_name} onChange={e=>change(["matched_name"],e.target.value)}/><input value={form.korean_name} onChange={e=>change(["korean_name"],e.target.value)}/></div>:<><h2>{form.matched_name}</h2><p className="muted">{form.korean_name}</p></>}</div><span className="status pending">{draft.status}</span></section>
    <section className="ai-summary-grid">
      <Card editing={editing} label="학명" value={form.scientific_name} onChange={v=>change(["scientific_name"],v)}/>
      <Card editing={editing} label="품종명(영문)" value={form.cultivar || ""} onChange={v=>change(["cultivar"],v)}/>
      <Card editing={editing} label="품종명(한글)" value={form.cultivar_ko || ""} onChange={v=>change(["cultivar_ko"],v)}/>
      <Card editing={editing} label="검역합격 발급번호" value={form.quarantine_number || ""} onChange={v=>change(["quarantine_number"],v)}/>
      <Card editing={editing} label="꽃 색상" value={form.classification?.flower_color || ""} onChange={v=>change(["classification","flower_color"],v)}/>
      <Card editing={editing} label="개화기" value={form.classification?.flowering_period || ""} onChange={v=>change(["classification","flowering_period"],v)}/>
      <Card editing={editing} label="초장" value={form.classification?.height || ""} onChange={v=>change(["classification","height"],v)}/>
      <Card editing={editing} label="원산지" value={form.origin || ""} onChange={v=>change(["origin"],v)}/>
      <Card editing={editing} label="번식방법" value={form.propagation_method || ""} onChange={v=>change(["propagation_method"],v)}/>
      <Card editing={editing} label="주요 용도" value={form.classification?.use || ""} onChange={v=>change(["classification","use"],v)}/>
    </section>
    <section className="panel"><h2>AI 작성 초안</h2><div className="draft-text-grid"><article><h3>품종의 특성 설명</h3><textarea rows="7" disabled={!editing} value={form.characteristics_draft} onChange={e=>change(["characteristics_draft"],e.target.value)}/></article><article><h3>품종의 육성과정</h3><textarea rows="7" disabled={!editing} value={form.breeding_process_draft} onChange={e=>change(["breeding_process_draft"],e.target.value)}/></article></div></section>
    <Photo role="overall" title="사진 1 · 품종 전체 모습" description="식물 또는 꽃대 전체 형태가 보이는 사진" images={overall} selected={form.selected_images?.overall} onSelect={id=>select("overall",id)} onUploaded={item=>setForm(c=>({...c,image_candidates:[...(c.image_candidates||[]),item],selected_images:{...(c.selected_images||{}),overall:item.id}}))}/>
    <Photo role="closeup" title="사진 2 · 꽃 근접 모습" description="꽃·잎의 색상과 형태가 잘 보이는 근접 사진" images={closeup} selected={form.selected_images?.closeup} onSelect={id=>select("closeup",id)} onUploaded={item=>setForm(c=>({...c,image_candidates:[...(c.image_candidates||[]),item],selected_images:{...(c.selected_images||{}),closeup:item.id}}))}/>
    <SupportingUploads form={form} setForm={setForm} setError={setError}/>
    <section className="panel warning-panel"><div className="ai-final-actions">{!editing?<button className="secondary-button icon-button" onClick={()=>setEditing(true)}><Pencil size={17}/>초안 수정</button>:<><button className="secondary-button icon-button" onClick={()=>{setForm(structuredClone(draft.result_data));setEditing(false);}}><X size={17}/>취소</button><button className="primary-button icon-button" onClick={save} disabled={saving}>{saving?<LoaderCircle className="spin" size={17}/>:<Save size={17}/>}수정 저장</button></>} {!editing&&<button className="primary-button" onClick={save}>신고 검토함에 저장</button>}</div></section>
  </div>;
}
function SupportingUploads({form,setForm,setError}) {
  const [busy,setBusy]=useState("");
  async function upload(role,event){
    const file=event.target.files?.[0]; event.target.value=""; if(!file)return;
    setBusy(role);setError("");
    try{
      const body=new FormData();body.append("role",role);body.append("file",file);
      const uploaded=await apiUpload("/api/ai-reports/upload",body);
      setForm(current=>({...current,manual_files:{...(current.manual_files||{}),[role]:{upload_id:uploaded.upload_id,name:uploaded.name,content_type:uploaded.content_type}}}));
    }catch(error){setError(error.message);}finally{setBusy("");}
  }
  const files=form.manual_files||{};
  return <section className="panel supporting-upload-panel"><h2>Invoice·검역서류 직접 첨부</h2><p className="muted">Drive에서 못 찾아도 전체 작업은 실패하지 않습니다. 필요한 파일만 직접 올릴 수 있습니다.</p><div className="supporting-upload-grid">
    <label className="secondary-button upload-button">{busy==="invoice"?"업로드 중...":"Invoice 업로드"}<input type="file" accept=".pdf,.xlsx,.xlsm" onChange={e=>upload("invoice",e)}/></label><span>{files.invoice?.name||"미첨부"}</span>
    <label className="secondary-button upload-button">{busy==="quarantine"?"업로드 중...":"검역·Phyto 업로드"}<input type="file" accept=".pdf,.jpg,.jpeg,.png" onChange={e=>upload("quarantine",e)}/></label><span>{files.quarantine?.name||"미첨부"}</span>
  </div></section>;
}

function Card({editing,label,value,onChange}){return <article className="ai-summary-card"><span>{label}</span>{editing?<input value={value} onChange={e=>onChange(e.target.value)}/>:<strong>{value}</strong>}</article>}
function Photo({role,title,description,images,selected,onSelect,onUploaded}) {
  const [uploading, setUploading] = useState(false);
  const [preview, setPreview] = useState(null);
  useEffect(() => {
    function onKeyDown(event) { if (event.key === "Escape") setPreview(null); }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);
  async function uploadImage(event) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    setUploading(true);
    try {
      const body = new FormData();
      body.append("role", role);
      body.append("file", file);
      const uploaded = await apiUpload("/api/ai-reports/upload", body);
      const id = `upload-${role}-${uploaded.upload_id}`;
      onUploaded({
        id,
        role,
        title: uploaded.name,
        source: "직접 업로드",
        source_url: "",
        preview_url: `${API_URL}${uploaded.preview_url}`,
        download_url: `${API_URL}${uploaded.preview_url}`,
        upload_id: uploaded.upload_id,
        recommended: true,
      });
    } catch (error) {
      alert(error.message);
    } finally {
      setUploading(false);
    }
  }
  return <>
    <section className="panel"><div className="ai-section-title"><ImageIcon size={20}/><h2>{title}</h2></div><p className="muted">{description}</p>
      <label className="secondary-button upload-button">{uploading?"업로드 중...":"내 사진 직접 업로드"}<input type="file" accept="image/*" disabled={uploading} onChange={uploadImage}/></label>
      {images.length===0&&<div className="empty-photo-message">자동 사진 후보가 없습니다. 위 버튼으로 직접 사진을 올려도 초안과 ZIP을 만들 수 있습니다.</div>}
      <div className="image-candidate-grid">{images.map(image=><article key={image.id} className={`image-candidate ${selected===image.id?"selected":""}`}>
        <button type="button" className="image-preview-button" onClick={()=>setPreview(image)}><img src={image.preview_url} alt={image.title}/><span className="image-zoom-label">클릭해서 크게 보기</span></button>
        <div className="image-candidate-body"><strong>{image.title}</strong><span>{image.source}</span><button type="button" className={`image-select-button ${selected===image.id?"selected":""}`} onClick={()=>onSelect(image.id)}>{selected===image.id&&<CheckCircle2 size={16}/>} {selected===image.id?"이 사진 사용 중":"이 사진 선택"}</button></div>
      </article>)}</div>
    </section>
    {preview&&<div className="image-lightbox" role="dialog" aria-modal="true" onClick={()=>setPreview(null)}><div className="image-lightbox-content" onClick={event=>event.stopPropagation()}>
      <button type="button" className="image-lightbox-close" onClick={()=>setPreview(null)}><X size={24}/></button>
      <img src={preview.download_url||preview.preview_url} alt={preview.title} onError={event=>{if(event.currentTarget.src!==preview.preview_url)event.currentTarget.src=preview.preview_url;}}/>
      <div className="image-lightbox-info"><strong>{preview.title}</strong><span>{preview.source}</span>{preview.source_url&&<a href={preview.source_url} target="_blank" rel="noreferrer">원본 출처 열기</a>}<button type="button" className="primary-button" onClick={()=>{onSelect(preview.id);setPreview(null);}}>이 사진 사용</button></div>
    </div></div>}
  </>;
}
