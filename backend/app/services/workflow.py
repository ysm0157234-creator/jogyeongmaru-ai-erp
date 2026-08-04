from __future__ import annotations
import io, json, re, zipfile
from datetime import datetime
from urllib.request import Request, urlopen
from app.core.config import get_settings
from app.services.drive_service import DriveFile, FOLDER_MIME, GoogleDriveService
from app.services.invoice_processor import create_invoice_extract_xlsx, extract_invoice_pdf_pages, filter_invoice_xlsx, pdf_contains, workbook_contains
from app.services.report_generator import build_breeding_document, build_characteristics_document, build_main_report, build_pdf_summary, build_sample_pledge_document
from app.services.shipment_parser import ShipmentMatch, find_variety_in_workbook

class RequiredFileMissingError(RuntimeError): pass

def norm(v): return re.sub(r"[^a-z0-9가-힣]+","",str(v or "").lower())
def safe(v): return re.sub(r'[\\/:*?"<>|]+','_',str(v)).strip()
def folder(x): return x.mime_type==FOLDER_MIME

def is_invoice(x):
    n=x.name.lower(); return not folder(x) and n.endswith(('.xlsx','.xlsm','.pdf')) and ('invoice' in n or '인보이스' in n)
def is_quarantine(x):
    n=x.name.lower(); return not folder(x) and n.endswith(('.pdf','.jpg','.jpeg','.png')) and any(k in n for k in ('검역','quarantine','phytosanitary','phyto'))

def split_shipment(shipment):
    m=re.match(r'^(.*?)[\s_-]*0*(\d+)$',str(shipment or '').strip())
    if not m: raise RequiredFileMissingError(f"Shipment 값에서 업체명과 컨테이너 번호를 분리할 수 없습니다: {shipment}")
    return m.group(1).strip(' _-'), int(m.group(2))

def match_folder(items,names):
    fs=[x for x in items if folder(x)]; targets=[norm(x) for x in names]
    for f in fs:
        if norm(f.name) in targets: return f
    for f in fs:
        fn=norm(f.name)
        if any(t and (t in fn or fn in t) for t in targets): return f
    return None

def supplier_folder(drive,root_id,supplier):
    names=[f'{supplier}_네덜란드',f'{supplier} 네덜란드',supplier]
    f=match_folder(drive.list_children(root_id),names)
    if not f: f=match_folder(drive.walk(root_id,max_depth=2,max_items=1500),names)
    if not f: raise RequiredFileMissingError(f"2025 수입에서 업체 폴더를 찾지 못했습니다: {supplier}_네덜란드")
    return f

def shipping_folder(drive,supplier):
    names=['Shipping document','Shipping documents','선적서류','무역서류']
    f=match_folder(drive.list_children(supplier.id),names)
    if not f: f=match_folder(drive.walk(supplier.id,max_depth=2,max_items=700),names)
    if not f: raise RequiredFileMissingError(f"{supplier.name} 안에서 Shipping document 폴더를 찾지 못했습니다.")
    return f

def container_numbers_from_name(name):
    """
    실제 폴더명 예:
    - 251212_container 7_MAEU262944634
    - 251208_container 3,5_COSU6437694570
    - 251222_container 9,10_MAEU263223238
    """
    value = str(name or "")
    match = re.search(
        r"(?i)container[\s_-]*([0-9,\s]+)",
        value,
    )
    if not match:
        return set()

    return {
        int(number)
        for number in re.findall(r"\d+", match.group(1))
    }


def container_folder(
    drive,
    shipping,
    number,
):
    children = drive.list_children(shipping.id)
    folders = [item for item in children if folder(item)]

    # 정확한 컨테이너 번호가 포함된 폴더만 선택
    exact = [
        item
        for item in folders
        if number in container_numbers_from_name(item.name)
    ]

    if exact:
        # 여러 개면 이름순 첫 번째
        return sorted(
            exact,
            key=lambda item: item.name.lower(),
        )[0]

    # 단순 이름 형태도 지원
    names = [
        f"Container {number}",
        f"Container{number}",
        f"Container_{number}",
    ]
    item = match_folder(folders, names)
    if item:
        return item

    available = ", ".join(
        item.name
        for item in folders[:20]
    )
    raise RequiredFileMissingError(
        f"{shipping.name} 안에서 Container {number} 폴더를 찾지 못했습니다. "
        f"확인된 폴더: {available}"
    )


def docs_in_container(
    drive,
    container,
):
    # 실제 구조상 인보이스와 Phyto는 Container 폴더 바로 아래에 있음
    direct_items = drive.list_children(container.id)

    invoices = sorted(
        [
            item
            for item in direct_items
            if is_invoice(item)
            and "freight invoice" not in item.name.lower()
        ],
        key=lambda item: (
            0 if "_invoice_" in item.name.lower() else 1,
            item.name.lower(),
        ),
    )

    quarantines = sorted(
        [
            item
            for item in direct_items
            if is_quarantine(item)
        ],
        key=lambda item: (
            0 if "phyto" in item.name.lower() else 1,
            item.name.lower(),
        ),
    )

    # 바로 아래에서 못 찾았을 때만 하위 폴더 제한 검색
    if not invoices or not quarantines:
        sub_items = drive.walk(
            container.id,
            max_depth=2,
            max_items=300,
        )

        if not invoices:
            invoices = sorted(
                [
                    item
                    for item in sub_items
                    if is_invoice(item)
                    and "freight invoice" not in item.name.lower()
                ],
                key=lambda item: item.name.lower(),
            )

        if not quarantines:
            quarantines = sorted(
                [
                    item
                    for item in sub_items
                    if is_quarantine(item)
                ],
                key=lambda item: item.name.lower(),
            )

    if not invoices:
        raise RequiredFileMissingError(
            f"{container.name} 안에서 일반 Invoice 파일을 찾지 못했습니다."
        )

    if not quarantines:
        raise RequiredFileMissingError(
            f"{container.name} 안에서 Phyto 또는 검역파일을 찾지 못했습니다."
        )

    return invoices[0], quarantines[0]


def parent_folder(drive,child,items):
    mp={x.id:x for x in items}
    for pid in child.parents or []:
        p=mp.get(pid)
        if p and folder(p): return p
        try:
            p=drive.get_metadata(pid)
            if folder(p): return p
        except Exception: pass
    return None

def fallback_tulipa(drive,root_id):
    items=drive.walk(root_id,max_depth=6,max_items=4000)
    for inv in sorted([x for x in items if is_invoice(x)],key=lambda x:x.name.lower()):
        try:
            data=drive.download(inv.id)
            ok=workbook_contains(data,['Tulipa']) if inv.name.lower().endswith(('.xlsx','.xlsm')) else pdf_contains(data,['Tulipa'])
            if not ok: continue
            c=parent_folder(drive,inv,items)
            if not c: continue
            sub=drive.walk(c.id,max_depth=3,max_items=700)
            q=next((x for x in sub if is_quarantine(x)),None)
            if q: return c,inv,q
        except Exception: continue
    raise RequiredFileMissingError('Shipment Overview에서 품종을 찾지 못했고, 2025 수입에서도 Tulipa 인보이스와 검역파일을 찾지 못했습니다.')

def image_url(data,role):
    sid=data.get('selected_images',{}).get(role)
    for x in data.get('image_candidates',[]):
        if x.get('id')==sid: return x.get('download_url') or x.get('preview_url') or ''
    raise RequiredFileMissingError(('전체 모습' if role=='overall' else '꽃 근접')+' 사진이 선택되지 않았습니다.')
def download_image(url):
    try:
        req=Request(url,headers={'User-Agent':'Mozilla/5.0 Jogyeongmaru-AI-ERP/6.0','Accept':'image/*'})
        with urlopen(req,timeout=40) as r:
            if not r.headers.get('Content-Type','').startswith('image/'): raise RequiredFileMissingError('사진 URL이 이미지가 아닙니다.')
            data=r.read(15*1024*1024)
            if len(data)<1000: raise RequiredFileMissingError('사진 데이터가 너무 작습니다.')
            return data
    except RequiredFileMissingError: raise
    except Exception as e: raise RequiredFileMissingError(f'사진을 내려받지 못했습니다: {e}') from e

def process_invoice(f,data,variety,shipment,values):
    try:
        if f.name.lower().endswith(('.xlsx','.xlsm')): return filter_invoice_xlsx(data,variety,shipment),f'06_{safe(variety)}_신고용_invoice.xlsx'
        if f.name.lower().endswith('.pdf'):
            out,_=extract_invoice_pdf_pages(data,variety); return out,f'06_{safe(variety)}_신고용_invoice.pdf'
    except Exception: pass
    return create_invoice_extract_xlsx(variety,shipment,values,f.name),f'06_{safe(variety)}_신고용_invoice_발췌.xlsx'

def run_workflow(variety_name,draft_data):
    s=get_settings(); drive=GoogleDriveService(); log=[]; supplier=None; shipping=None
    shipment_bytes=drive.download(s.shipment_overview_file_id)
    try:
        match=find_variety_in_workbook(shipment_bytes,variety_name)
        supplier_name,num=split_shipment(match.shipment)
        supplier=supplier_folder(drive,s.import_2025_folder_id,supplier_name)
        shipping=shipping_folder(drive,supplier)
        container=container_folder(drive,shipping,num)
        invoice,quarantine=docs_in_container(drive,container)
        log += [f'H열 Shipment: {match.shipment}',f'업체 폴더: {supplier.name}',f'Shipping document: {shipping.name}',f'Container: {container.name}']
        mode='shipment_overview_2025_route'
    except LookupError:
        container,invoice,quarantine=fallback_tulipa(drive,s.import_2025_folder_id)
        match=ShipmentMatch(sheet_name='2025 수입 Tulipa 보조검색',row_number=0,description=variety_name,shipment=container.name,values={'품종명':variety_name},source='import_2025_tulipa_fallback')
        mode='import_2025_tulipa_fallback'; log.append(f'Tulipa 인보이스 Container 사용: {container.name}')
    inv_data=drive.download(invoice.id); qua_data=drive.download(quarantine.id)
    ou=image_url(draft_data,'overall'); cu=image_url(draft_data,'closeup')
    if ou==cu: raise RequiredFileMissingError('전체 모습과 꽃 근접 사진은 서로 달라야 합니다.')
    oi,ci=download_image(ou),download_image(cu)
    final=draft_data.get('matched_name',variety_name); ko=draft_data.get('korean_name','튤립 썬러버'); sci=draft_data.get('scientific_name',"Tulipa 'Sun Lover'")
    ch=draft_data.get('characteristics_draft',''); br=draft_data.get('breeding_process_draft','')
    if not ch.strip() or not br.strip(): raise RequiredFileMissingError('품종 특성 설명 또는 육성과정이 비어 있습니다.')
    inv_out,inv_name=process_invoice(invoice,inv_data,variety_name,match.shipment,match.values)
    main=build_main_report(final,ko,sci,match.shipment,ch,br,oi,ci)
    cdoc=build_characteristics_document(final,ko,sci,ch,oi,ci); bdoc=build_breeding_document(final,ko,br); pledge=build_sample_pledge_document(final,ko)
    summary=build_pdf_summary(final,sci,match.shipment,invoice.name,quarantine.name)
    manifest={'generated_at':datetime.utcnow().isoformat()+'Z','variety':variety_name,'search_mode':mode,'shipment':match.shipment,'supplier_folder':supplier.name if supplier else None,'shipping_folder':shipping.name if shipping else None,'container_folder':container.name,'invoice':invoice.name,'quarantine':quarantine.name,'search_log':log}
    buf=io.BytesIO(); base=safe(variety_name)
    with zipfile.ZipFile(buf,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr(f'{base}/01_생산수입판매신고서_검토안.docx',main); z.writestr(f'{base}/02_품종특성설명.docx',cdoc); z.writestr(f'{base}/03_품종육성과정.docx',bdoc); z.writestr(f'{base}/04_시료제출확약서.docx',pledge); z.writestr(f'{base}/05_{safe(quarantine.name)}',qua_data); z.writestr(f'{base}/{inv_name}',inv_out); z.writestr(f'{base}/07_품종전체사진.jpg',oi); z.writestr(f'{base}/08_꽃근접사진.jpg',ci); z.writestr(f'{base}/09_처리요약.pdf',summary); z.writestr(f'{base}/manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2,default=str))
    return buf.getvalue(),manifest
