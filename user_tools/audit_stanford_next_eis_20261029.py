"""Preselected search: W5 Diag_2, W5 Diag_3, then W9 Diag_2."""
from pathlib import Path
import hashlib,json,re
import numpy as np
import openpyxl,requests
from user_tools.fetch_stanford_aging_case_20261029 import listing
from user_tools.workbench.engineering_eis_audit import lin_kk

OUT=Path('outputs/eis_bms_validation/stanford_candidate_eis_20261029')
DATA=Path('data/public/stanford_aging_w9_diag2_eis_20261029')

def main():
    OUT.mkdir(parents=True,exist_ok=True);DATA.mkdir(parents=True,exist_ok=True)
    folders=['diagnostic_tests/Diag_2/EIS_test','diagnostic_tests/Diag_3/EIS_test',
             'diagnostic_tests/Diag_2/HPPC_test','diagnostic_tests/Diag_2/Capacity_test','cycling_tests/Cycling_2/W9']
    inventory={};failures=[]
    for folder in folders:
        try:inventory[folder]=listing(folder)
        except Exception as exc:failures.append({'folder':folder,'error':repr(exc)});inventory[folder]=[]
    def names(folder,cell):return [e['attributes']['name'] for e in inventory[folder] if f'_{cell}_' in e['attributes']['name']]
    candidates=[{'cell':'W5','diagnostic':'Diag_2','eis_files':names(folders[0],'W5')},
                {'cell':'W5','diagnostic':'Diag_3','eis_files':names(folders[1],'W5')},
                {'cell':'W9','diagnostic':'Diag_2','eis_files':names(folders[0],'W9'),
                 'hppc_files':names(folders[2],'W9'),'capacity_files':names(folders[3],'W9'),
                 'cycling_files_count':len(names(folders[4],'W9'))}]
    spectra=[]
    for entry in inventory[folders[0]]:
        name=entry['attributes']['name']
        if '_W9_' not in name:continue
        path=DATA/name
        try:
            if not path.exists():
                resp=requests.get(entry['links']['download'],timeout=90);resp.raise_for_status();content=resp.content
                if not content.startswith(b'PK') or (entry['attributes']['size'] is not None and len(content)!=entry['attributes']['size']):raise ValueError('download not complete XLSX')
                path.write_bytes(content)
            wb=openpyxl.load_workbook(path,read_only=True,data_only=True)
            sheet=next(s for s in wb if s.title.startswith('ACIM_'));lines=sheet.iter_rows(values_only=True);head=list(next(lines));indices=[head.index(k) for k in ('Freq','Zmod','Zphz')]
            arr=np.asarray([[row[i] for i in indices] for row in lines if all(isinstance(row[i],(int,float)) for i in indices)],float)
            channel=next(s for s in wb if s.title.startswith('Channel_'));lines=channel.iter_rows(values_only=True);head=list(next(lines));col=head.index('Date_Time');times=[row[col] for row in lines if row[col] is not None];wb.close()
            f=arr[:,0];z=arr[:,1]*np.exp(1j*np.deg2rad(arr[:,2]));bands={}
            for label,hi in [('full',20000),('under_500Hz',500)]:
                idx=(f>0)&(f<=hi);_,diag=lin_kk(f[idx],z[idx],True);bands[label]={'points':int(idx.sum()),**diag}
            spectra.append({'file':name,'soc_percent':int(re.search(r'SOC(\d+)',name).group(1)),
                'sha256_local':hashlib.sha256(path.read_bytes()).hexdigest(),'publisher_sha256':entry['attributes']['extra']['hashes'].get('sha256'),
                'start_time':str(times[0]) if times else None,'end_time':str(times[-1]) if times else None,
                'raw_columns':['Freq','Zmod','Zphz'],'unit_interpretation':'Hz, ohm, degrees; complex = magnitude exp(j phase)',
                'bands':bands})
        except Exception as exc:failures.append({'file':name,'error':repr(exc)})
    complete=len(spectra)==3 and all(s['bands']['full']['screening_pass'] for s in spectra)
    result={'selection_rule':'W5 Diag_2, W5 Diag_3, then W9 Diag_2; quality and metadata before dynamic errors',
      'candidates':candidates,'w9_spectra':spectra,'failures':failures,
      'w9_screen_pass_all_full':complete,'selected':None,
      'status':'未冻结：缺少 W5 EIS，W9 需要通过质量及诊断-动态时间、SOC/温度/状态审核',
      'screen_scope':'fixed existing Lin-KK engineering screen, not proof data invalid; under 500 Hz is exploratory; no gate changed'}
    (OUT/'candidate_audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
