import shutil, openpyxl
from copy import copy
from openpyxl.styles import Alignment, PatternFill, Font, Border, Side
D='/home/claude/work/out/'
SRC=D+'광고검수_담당자vsClaude_비교_final.xlsx'
OUT=D+'광고검수_담당자vsClaude_비교_v6.xlsx'
shutil.copy(SRC,OUT)
wb=openpyxl.load_workbook(OUT)
ws=wb['광고검수의견']; ws2=wb['항목별점검표']; ws3=wb['요약·기준·이력']

CRIT=('담당자 회신(2026-11-06) 완화 기준: ① "개수 제한없이"는 협회 심의에서 "무제한"의 대체 표현으로 인정(지적 대상 아님) '
 '② 상품의 보장내용·보험료 구조에 부합하는 객관적 사실 표현(예: 평생 사망보장, 7년간 보험료 변동 NO)은 지적 대상 아님 '
 '③ 카드뉴스의 보장 한도·횟수, 보험·납입기간, 지급사유·금액 미기재는 감독당국 협의·심의 경험상 예외적 용인 '
 '④ 이벤트 배너 내 지급조건·구간별 차등 지급 미표시는 후속 페이지에서 안내하는 구조면 배너만 보고 지적하지 않음(광고 전체 맥락 종합)')

# row key -> dict
R={}
def put(k,**kw): R[k]=kw
put('A',crit='② ④',chg='항목 변경',res='적격',cmp='일치',
 txt='3-1 △→○: 배너의 "최대 3만원·100% 당첨" 지급조건·구간별 가액은 상세 페이지에서 안내하는 구조(회신 ④)로 보아 지적하지 않음. 4-3·4-10은 "7년간 보험료 변동 NO"를 객관적 사실 표현(회신 ②)으로 보아 제외하되, "100% 당첨" 조건 병기 권고는 △로 유지. 종합 결과는 변경 없음.',
 alt='-',
 items=[('3-1','○','회신 ④: 지급조건·구간별 가액을 상세 페이지에서 안내하는 구조. 배너에 "조건은 상세 참조" 병기는 권고 수준.'),
        ('4-3','△','회신 ②: "7년간 보험료 변동 NO"는 상품 구조에 부합하는 객관적 사실이면 지적 제외. "100% 당첨" 조건 병기 권고만 남음.'),
        ('4-10','△','4-3과 동일. "7년간 보험료 변동 NO" 부분은 제외, "100% 당첨" 부분 유지.')])
put('B',crit='① ③',chg='항목 변경',res='시정요구',cmp='불일치',
 txt='4-1 ×→△: "개수 제한없이"는 협회 인정 대체 표현(회신 ①)이고 91일·1년 50% 지급제한이 하단에 병기되어 있어 지급제한 비중 개선 권고로 낮춤. 4-3·4-4 △→○: "제한 없는 보장" 오인 지적은 회신 ①에 따라 제외. 2-1·2-4·2-9·3-7 ×는 유지: 회신 ③은 보장 한도·횟수 등 내용 미기재만 용인하는 것으로 읽혀, 약관 권유·승환·예금자보호 같은 필수 개괄 안내 생략까지 용인하는지는 확인되지 않음. 따라서 시정요구 유지.',
 alt='적격(일치): 회신 ③을 카드뉴스의 필수 개괄 안내 생략까지 용인하는 취지로 확대 해석하면 2-1·2-4·2-9·3-7이 △로 내려가 담당자 적격과 일치. 담당자에게 해당 범위 확인 필요.',
 items=[('4-1','△','회신 ①: "개수 제한없이"는 무제한의 대체 표현으로 인정. 지급제한(91일, 1년 50%)이 병기되어 있어 비중 개선 권고로 하향.'),
        ('4-3','○','회신 ①: "개수 제한없이"는 지적 대상이 아님.'),
        ('4-4','○','회신 ①: 제한 없는 보장 오인 지적 제외.')])
put('D',crit='③ ④',chg='항목 변경',res='시정요구',cmp='불일치',
 txt='2-5·4-1 ×→△: 카드뉴스의 보장 한도·횟수·지급제한 미기재는 예외 용인 대상(회신 ③)이고 지급조건은 연결 영상·후속 페이지 구조(회신 ④)로 판단하여 낮춤. 2-3(약관상 상품명 없음)은 회신에 해당 기준이 없어 × 유지. 2-1·2-4·2-9·3-7 ×는 B와 같은 이유로 유지. 종합 시정요구 유지.',
 alt='시정요구(불일치 유지): 회신 ③을 필수 개괄 안내까지 확대 해석해도 2-3 상품명 누락이 남아 시정요구. 담당자가 상품명 표기를 어떻게 보는지 확인 필요.',
 items=[('2-5','△','회신 ③: 카드뉴스의 보장 한도·횟수·지급제한 미기재는 예외적 용인. 연결 영상에서 안내되는지 확인 필요.'),
        ('4-1','△','회신 ③·④: 보장 제한 미표기는 예외 용인 대상이며 후속 영상·페이지에서 안내하는 구조면 배너만으로 지적하지 않음.')])
put('H',crit='①',chg='사유 축소',res='시정요구',cmp='일치',
 txt='4-1 ×는 유지하되 지적 사유를 "개수 제한없이 표현"이 아니라 "개수 제한 표현 시 지급제한 병기(별지 제9호 치아보험 기준 ①)" 누락으로 한정. 표현 자체는 회신 ①에 따라 지적하지 않음. 4-5·4-9 ×가 있어 결과는 변경 없음.',
 alt='-',items=[('4-1','×','회신 ①: 표현 자체는 지적 제외. 지급제한 병기 누락만 지적 사유로 유지(별지 제9호 ①).')])
put('I',crit='①',chg='사유 축소',res='시정요구',cmp='일치',
 txt='4-1 ×는 유지하되 사유를 지급제한(91일, 1년 50%) 병기 누락으로 한정. "개수 제한 없는 치아보험" 표현 자체는 지적 제외(회신 ①). 3-5·4-5·4-9 ×가 있어 결과 변경 없음.',
 alt='-',items=[('4-1','×','회신 ①: 표현 자체는 지적 제외. 지급제한 병기 누락과 "보장 한도 매년 새로 채워져요"의 조건 부재만 유지.')])
put('S',crit='①',chg='사유 축소',res='시정요구',cmp='일치',
 txt='"개수 제한없이 보장" 표현은 회신 ①에 따라 지적 제외. 다만 "금으로 충전치료해도 전부 보장", "몇 번이든 충전치료 보장"은 "개수 제한없이"와 다른 표현이고 같은 화면의 "1년 이내 50%"와 충돌하므로 4-1·4-3 ×는 유지. 결과 변경 없음.',
 alt='-',items=[('4-1','×','회신 ①: "개수 제한없이" 표현은 제외. "전부 보장"·"몇 번이든"과 50% 보장의 충돌은 유지.'),
                ('4-3','×','"전부 보장"은 회신 ①의 대체 표현 범위에 포함되지 않아 유지.')])
put('T',crit='①',chg='사유 축소',res='시정요구',cmp='일치',
 txt='4-1 △에서 "충전치료 개수 제한 없이" 부분은 회신 ①에 따라 제외. "가입 즉시 암진단금 100% 보장개시" 조건 확인 사항은 유지. 결과 변경 없음.',
 alt='-',items=[('4-1','△','회신 ①: "개수 제한 없이" 부분 제외. 즉시 보장 표현의 감액 조건 확인만 남음.')])
put('U',crit='①',chg='사유 축소',res='시정요구',cmp='불일치',
 txt='"개수 제한없이" 표현은 회신 ①에 따라 지적 제외하나, "전~부 보장해드려요", "모두 보장"(4-3 ×)과 "3% 할인" 기준 부재(3-5·4-5 ×)는 회신 기준에 해당하지 않아 유지. 시정요구 유지, 담당자 적격과 불일치도 유지.',
 alt='-',items=[('4-1','△','회신 ①: "개수 제한없이" 표현은 제외. 50% 보장 누락 소재의 지급제한 병기는 유지.'),
                ('4-3','×','"전~부 보장", "모두 보장"은 회신 ①의 대체 표현이 아니어서 유지. "개수 제한없이" 부분만 제외.')])
put('W',crit='①',chg='사유 축소',res='적격',cmp='일치',
 txt='4-3 △에서 "충전치료 개수 제한 없이" 부분은 회신 ①에 따라 제외. "전부 보장됩니다"와 4-9 "라이나는 없습니다" 비교 암시는 유지. 결과 변경 없음.',
 alt='-',items=[('4-3','△','회신 ①: "개수 제한 없이" 부분 제외. "전부 보장됩니다" 표현 순화 권고만 남음.')])
NOTE_NA={'C':'해당 없음(종신 리플렛)','E':'해당 없음','F':'④ 참고: 배너 소재, 연결 페이지 구조는 기존 판정에 이미 반영','G':'해당 없음','J':'③ 검토: 그림문자(MMS 이미지)는 카드뉴스가 아니어서 적용하지 않음. 승환·면책 안내를 수정 후 삭제한 점은 회신 기준에 해당 없음',
 'K':'해당 없음','L':'④ 참고: 검색광고, 연결 페이지 구조는 기존 판정에 이미 반영','M':'④ 참고: 팝업, 기존 판정에 이미 반영','N':'해당 없음','O':'해당 없음','P':'① ② 검토: "수술할 때마다 정액 보장"은 연결 랜딩의 "동일 질병 365일 1회 한도"와 어긋나 회신 ②(상품 구조에 부합하는 표현)에 해당하지 않음',
 'Q':'해당 없음','R':'해당 없음','V':'④ 검토: 설계사 대상 이벤트 이미지, 지급조건은 기존 판정에 △로 반영. 환급률 기준은 회신 대상 아님','X':'해당 없음','Y':'④ 검토: 위와 동일','Z':'④ 검토: 포인트 지급조건이 LP에서 안내되는지는 판독 불가라 △ 유지'}
heads=['담당자 회신 완화기준 적용 검토','완화 반영 후 변경 여부','완화 반영 후 Claude 결과','완화 반영 후 담당자 비교','완화 기준 반영에 따른 변경 항목·의견','확대 해석 시 결과(조건부)']
base=15
for i,h in enumerate(heads):
    c=ws.cell(1,base+i,h); n=ws['N1']
    c.font=copy(n.font); c.fill=copy(n.fill); c.alignment=copy(n.alignment); c.border=copy(n.border)
    ws.column_dimensions[openpyxl.utils.get_column_letter(base+i)].width=[30,16,16,16,70,50][i]
GREEN=PatternFill('solid',fgColor='E2EFDA'); YEL=PatternFill('solid',fgColor='FFF2CC'); RED=PatternFill('solid',fgColor='F8CBAD')
for r in range(2,28):
    k=ws.cell(r,2).value[0]
    d=R.get(k)
    if d: vals=[d['crit']+' '+('적용' if d['chg']!='사유 축소' else '적용(사유 축소)'),d['chg'],d['res'],d['cmp'],d['txt'],d['alt']]
    else: vals=[NOTE_NA.get(k,'해당 없음'),'변경 없음',ws.cell(r,6).value,ws.cell(r,7).value,'-','-']
    for i,v in enumerate(vals):
        c=ws.cell(r,base+i,v); n=ws.cell(r,14)
        c.font=copy(n.font); c.alignment=copy(n.alignment); c.border=copy(n.border)
    if d and d['chg']=='항목 변경': ws.cell(r,16).fill=YEL
    ws.cell(r,17).fill = GREEN if ws.cell(r,17).value=='적격' else RED
    ws.cell(r,18).fill = GREEN if ws.cell(r,18).value=='일치' else RED
    if d and len(d['txt'])>200: ws.row_dimensions[r].height=max(ws.row_dimensions[r].height or 15,330)
ws.auto_filter.ref='A1:T27'

# checklist sheet
for ci,h in ((10,'완화 기준 반영 후 판정'),(11,'완화 기준 반영 의견(담당자 회신 2026-11-06)')):
    c=ws2.cell(1,ci,h); n=ws2['I1']
    c.font=copy(n.font); c.fill=copy(n.fill); c.alignment=copy(n.alignment); c.border=copy(n.border)
ws2.column_dimensions['J'].width=18; ws2.column_dimensions['K'].width=70
idx={}
for r in range(2,ws2.max_row+1): idx[(ws2.cell(r,1).value,ws2.cell(r,3).value)]=r
for k,d in R.items():
    for no,j,why in d['items']:
        r=idx[(k,no)]
        ws2.cell(r,10,j); ws2.cell(r,11,why)
        for ci in (10,11):
            n=ws2.cell(r,9); c=ws2.cell(r,ci); c.font=copy(n.font); c.alignment=copy(n.alignment); c.border=copy(n.border)
        if j!=ws2.cell(r,6).value: ws2.cell(r,10).fill=YEL
ws2.auto_filter.ref='A1:K%d'%ws2.max_row

# difference sheet
ds=wb.create_sheet('담당자vsClaude 상이')
cols=['접수번호','광고명','담당자 결과','담당자 의견','Claude 결과(기존)','완화 기준 반영 후 Claude 결과','완화 반영 후 담당자 비교','결과가 다른 핵심 사유','쟁점 점검표 항목(×·△)','판단 규정','완화 기준 영향','확대 해석 시 결과(조건부)','권고 수정안','담당자와 확인할 사항']
KEY={'B':'카드뉴스의 필수 개괄 안내(약관 권유·승환·예금자보호) 생략을 담당자가 용인하는 범위인지',
     'D':'상품명(약관상 명칭) 대신 약칭·마케팅 용어만 쓴 점과 카드뉴스 필수안내 생략을 용인하는지, 연결 영상 제출 여부',
     'J':'수정 후 삭제된 승환 유의·면책·감액 안내를 이미지 광고에서 생략할 수 있다고 보는지, "업계 최초" 증빙',
     'P':'"수술비보험" 표현을 주계약처럼 읽힌다고 보는지(O 행에서는 담당자가 시정요구), "수술할 때마다"와 랜딩 한도의 불일치',
     'U':'"3% 할인" 비교 기준 없이 승인 가능한지, "전~부 보장"을 S 건과 달리 허용하는지'}
for i,h in enumerate(cols):
    c=ds.cell(1,i+1,h); n=ws['A1']
    c.font=copy(n.font); c.fill=copy(n.fill); c.alignment=copy(n.alignment); c.border=copy(n.border)
rr=2
for r in range(2,28):
    if ws.cell(r,7).value!='불일치': continue
    k=ws.cell(r,2).value[0]; d=R.get(k)
    after=ws.cell(r,17).value
    vals=[ws.cell(r,1).value,ws.cell(r,2).value,ws.cell(r,3).value,ws.cell(r,4).value or '(의견 없음, 적격)',
          ws.cell(r,6).value,after,ws.cell(r,18).value,ws.cell(r,12).value,ws.cell(r,9).value,ws.cell(r,10).value,
          (d['txt'] if d else NOTE_NA.get(k,'-')),(d['alt'] if d else '-'),ws.cell(r,13).value,KEY[k]]
    for i,v in enumerate(vals):
        c=ds.cell(rr,i+1,v); n=ws.cell(r,14)
        c.font=copy(n.font); c.alignment=copy(n.alignment); c.border=copy(n.border)
    rr+=1
for i,w in enumerate([18,32,12,30,14,16,16,60,40,40,60,45,60,45]): ds.column_dimensions[openpyxl.utils.get_column_letter(i+1)].width=w
for r in range(2,rr): ds.row_dimensions[r].height=330
ds.row_dimensions[1].height=32
ds.freeze_panes='C2'; ds.auto_filter.ref='A1:N%d'%(rr-1)
ds.cell(rr+1,1,'※ 이 시트는 담당자 결과와 Claude 결과(적격/시정요구)가 다른 건만 모은 것입니다. 광고검수의견 시트의 같은 행 값을 옮겨 적은 것이라, 원본 시트를 고치면 이 시트도 함께 고쳐야 합니다.')
ds.cell(rr+2,1,CRIT)
for c in (ds.cell(rr+1,1),ds.cell(rr+2,1)): c.alignment=Alignment(wrap_text=False,vertical='top')
nd=rr-2+0

# summary sheet
hist=[r for r in range(1,ws3.max_row+1) if str(ws3.cell(r,2).value).startswith('U~Z 6건')][0]
ws3.insert_rows(hist+1)
for ci in (1,2):
    s=ws3.cell(hist,ci); t=ws3.cell(hist+1,ci); t.font=copy(s.font); t.alignment=copy(s.alignment); t.border=copy(s.border); t.fill=copy(s.fill)
ws3.cell(hist+1,1,'2026-11-13'); ws3.cell(hist+1,2,'담당자 회신(광고 심의 AI 활용 관련 준법 의견) 완화 기준 반영 검토. 광고검수의견 O~T열, 항목별점검표 J~K열, "담당자vsClaude 상이" 시트 추가. 기존 A~N열과 점검표 A~I열은 변경하지 않음.')
last=ws3.max_row
def addrow(r,a,b):
    ws3.cell(r,1,a); ws3.cell(r,2,b)
    for ci in (1,2):
        s=ws3.cell(last,ci); c=ws3.cell(r,ci); c.font=copy(s.font); c.alignment=copy(s.alignment); c.border=copy(s.border)
    ws3.row_dimensions[r].height=ws3.row_dimensions[last].height
addrow(last+1,'담당자 회신 완화 기준',CRIT)
addrow(last+2,'완화 반영 판단 메모','해석 범위: 회신 ③은 카드뉴스의 "보장 한도·횟수, 보험·납입기간, 지급사유·금액" 미기재를 용인한다고 읽어 필수 개괄 안내(약관 권유·승환·예금자보호) 생략은 용인 범위로 보지 않았음. 이 해석이 담당자 의도와 다르면 B는 적격으로 바뀜(O~T열의 "확대 해석 시 결과"). 회신 ①은 표현 자체를 지적하지 않는 것이며, 치아보험 심의기준(별지 제9호 ①)의 지급제한 병기 요구까지 없애는 것으로 보지 않았음. 회신은 사진 캡처본이라 문구를 직접 확인했고 심의 사례 원문은 확인하지 못함.')
# summary table rows after existing summary: use free rows? append at end
addrow(last+3,'완화 반영 후 적격 / 시정요구','=COUNTIF(광고검수의견!Q:Q,"적격")&" / "&COUNTIF(광고검수의견!Q:Q,"시정요구")')
addrow(last+4,'완화 반영 후 일치 / 불일치','=COUNTIF(광고검수의견!R:R,"일치")&" / "&COUNTIF(광고검수의견!R:R,"불일치")')
wb.save(OUT); print('saved',rr-2)
