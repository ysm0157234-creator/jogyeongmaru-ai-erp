from __future__ import annotations
import io, json, re, zipfile
from datetime import datetime
from app.core.config import get_settings
from app.services.drive_service import GoogleDriveService, DriveFile
from app.services.shipment_parser import ShipmentMatch, find_variety_in_workbook
from app.services.invoice_processor import workbook_contains, pdf_contains, filter_invoice_xlsx, extract_invoice_pdf_pages, create_invoice_extract_xlsx
from app.services.report_generator import build_docx, build_pdf_summary

SUNLOVER={"matched_name":"Tulipa spp. Sunlover","korean_name":"튤립 썬러버","scientific_name":"Tulipa 'Sun Lover'","characteristics":"겹꽃형 튤립 품종으로 개화 초기에는 황금빛 노란색을 띠고 개화가 진행되면서 주황빛 적색으로 변화한다.","breeding_process":"상기 품종을 국내에 수입·유통하기 위하여 네덜란드 수출업체를 통해 적법하게 구근을 수입하였다."}

def safe_name(v): return re.sub(r'[\\/:*?"<>|]+','_',v).strip()
def norm(v): return re.sub(r'[^a-z0-9가-힣]+','',str(v or '').lower())
def vterms(name): return [name,name.replace('Sunlover','Sun Lover'),name.replace('Sun Lover','Sunlover'),name.split()[-1]]

def fallback_2026(drive, folder_id, variety_name):
    files=drive.walk(folder_id,max_depth=7)
    docs=[f for f in files if f.mime_type!='application/vnd.google-apps.folder' and f.name.lower().endswith(('.xlsx','.xlsm','.pdf'))]
    docs.sort(key=lambda f:(0 if f.name.lower().endswith(('.xlsx','.xlsm')) else 1,f.name.lower()))
    for f in docs:
        try:
            data=drive.download(f.id)
            ok=workbook_contains(data,vterms(variety_name)) if f.name.lower().endswith(('.xlsx','.xlsm')) else pdf_contains(data,vterms(variety_name))
            if not ok: continue
            shipment=''
            for candidate in [f.name]+[p.name for p in files if p.id in set(f.parents or [])]:
                m=re.search(r'\b[A-Z]{4}\d{7}\b|\bH\d{5,}\b|\b[A-Z]{2,8}[-_ ]?\d{2,}\b',candidate,re.I)
                if m: shipment=m.group(0).strip(); break
            if not shipment: shipment=re.sub(r'\.(xlsx|xlsm|pdf)$','',f.name,flags=re.I)
            return ShipmentMatch(f.name,0,variety_name,shipment,{"품종명":variety_name,"검색 원본":f.name,"검색 방식":"2026 수입 폴더 내부 검색"},"import_2026_fallback"),f,data,files
        except Exception:
            continue
    raise LookupError(f"Shipment Overview와 2026 수입 폴더 모두에서 '{variety_name}' 품종을 찾지 못했습니다.")

def invoice_candidates(files,shipment,matched_file=None):
    key=norm(shipment); parents=set(matched_file.parents or []) if matched_file else set(); scored=[]
    for f in files:
        if f.mime_type=='application/vnd.google-apps.folder' or not any(x in f.name.lower() for x in ('invoice','인보이스')): continue
        score=(100 if key and key in norm(f.name) else 0)+(80 if parents.intersection(f.parents or []) else 0)+(10 if f.name.lower().endswith(('.xlsx','.xlsm')) else 0)
        scored.append((score,f))
    return [f for _,f in sorted(scored,key=lambda x:(-x[0],x[1].name.lower()))]

def run_workflow(variety_name):
    s=get_settings(); drive=GoogleDriveService(); log=[]; matched_file=None; matched_data=None
    shipment_bytes=drive.download(s.shipment_overview_file_id)
    try:
        match=find_variety_in_workbook(shipment_bytes,variety_name); log.append('Shipment Overview에서 품종과 Shipment를 찾았습니다.'); files=drive.walk(s.import_2026_folder_id,max_depth=7)
    except LookupError as e:
        log.append(str(e)); match,matched_file,matched_data,files=fallback_2026(drive,s.import_2026_folder_id,variety_name); log.append(f'2026 수입 폴더에서 품종 발견: {matched_file.name}')
    candidates=invoice_candidates(files,match.shipment,matched_file)
    selected=None; out_name=None; out_data=None; mode=''
    for f in candidates:
        try:
            data=drive.download(f.id)
            if f.name.lower().endswith(('.xlsx','.xlsm')) and workbook_contains(data,vterms(variety_name)):
                out_data=filter_invoice_xlsx(data,variety_name,match.shipment); out_name=f'{safe_name(variety_name)}_신고용_invoice.xlsx'; mode='원본 XLSX에서 해당 품종 행만 남김'; selected=f; break
            if f.name.lower().endswith('.pdf'):
                out_data,pages=extract_invoice_pdf_pages(data,variety_name); out_name=f'{safe_name(variety_name)}_신고용_invoice.pdf'; mode=f'원본 PDF에서 품종 포함 페이지 {pages}장 추출'; selected=f; break
        except Exception: continue
    if out_data is None and matched_file and matched_data:
        try:
            if matched_file.name.lower().endswith(('.xlsx','.xlsm')):
                out_data=filter_invoice_xlsx(matched_data,variety_name,match.shipment); out_name=f'{safe_name(variety_name)}_신고용_검색원본.xlsx'; mode=f'2026 수입 검색 원본에서 품종 행 추출: {matched_file.name}'
            else:
                out_data,pages=extract_invoice_pdf_pages(matched_data,variety_name); out_name=f'{safe_name(variety_name)}_신고용_검색원본.pdf'; mode=f'2026 수입 검색 PDF에서 품종 페이지 {pages}장 추출'
        except Exception: pass
    if out_data is None:
        out_data=create_invoice_extract_xlsx(variety_name,match.shipment,match.values,selected.name if selected else (matched_file.name if matched_file else None)); out_name=f'{safe_name(variety_name)}_신고용_invoice_발췌.xlsx'; mode='검색 결과 기반 신고용 인보이스 발췌본 신규 생성'
    docx=build_docx(SUNLOVER['matched_name'],SUNLOVER['korean_name'],SUNLOVER['scientific_name'],match.shipment,SUNLOVER['characteristics'],SUNLOVER['breeding_process'])
    pdf=build_pdf_summary(SUNLOVER['matched_name'],SUNLOVER['korean_name'],SUNLOVER['scientific_name'],match.shipment,SUNLOVER['characteristics'],SUNLOVER['breeding_process'])
    manifest={"generated_at":datetime.utcnow().isoformat()+"Z","variety":variety_name,"search_log":log,"shipment_result":{"source":match.source,"sheet_or_file":match.sheet_name,"row":match.row_number,"description":match.description,"shipment":match.shipment,"values":match.values},"shipment_overview":{"shipment":match.shipment},"invoice_candidates":[{"id":f.id,"name":f.name} for f in candidates],"selected_invoice":{"id":selected.id,"name":selected.name} if selected else None,"invoice_processing":mode}
    buf=io.BytesIO(); folder=safe_name(variety_name)
    with zipfile.ZipFile(buf,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr(f'{folder}/신고서_검토안.docx',docx); z.writestr(f'{folder}/처리요약.pdf',pdf); z.writestr(f'{folder}/{out_name}',out_data); z.writestr(f'{folder}/manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2,default=str))
    return buf.getvalue(),manifest
