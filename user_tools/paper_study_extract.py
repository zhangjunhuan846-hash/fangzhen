"""Archive user-supplied papers and extract page-labelled text, without editing PDFs."""
from pathlib import Path
import hashlib
import json
import shutil
from pypdf import PdfReader


FILES={
 'eis_2025':'Hallemans_2025_J._Electrochem._Soc._172_060507.pdf',
 'boed_2019':'NeurIPS-2019-variational-bayesian-optimal-experimental-design-Paper.pdf',
 'basq_2022':'NeurIPS-2022-fast-bayesian-inference-with-batch-bayesian-quadrature-via-kernel-recombination-Paper-Conference.pdf',
 'nehvi_2021':'NeurIPS-2021-parallel-bayesian-optimization-of-multiple-noisy-objectives-with-expected-hypervolume-improvement-Paper.pdf',
 'logei_2023':'NeurIPS-2023-unexpected-improvements-to-expected-improvement-for-bayesian-optimization-Paper-Conference.pdf',
 'be_cbo_2024':'tian24g.pdf',
 'imfbo_2024':'fan24a.pdf',
 'sc_cp_2024':'NeurIPS-2024-self-calibrating-conformal-prediction-Paper-Conference.pdf',
}


def main():
    root=Path(__file__).resolve().parents[1];archive=root/'papers/workstation_methods_20261012'
    output=root/'outputs/paper_study_20261012';archive.mkdir(parents=True,exist_ok=True);output.mkdir(parents=True,exist_ok=True)
    records=[]
    for key,name in FILES.items():
        source=Path.home()/'Downloads'/name;dest=archive/name
        raw=source.read_bytes();digest=hashlib.sha256(raw).hexdigest()
        if dest.exists() and hashlib.sha256(dest.read_bytes()).hexdigest()!=digest:raise ValueError('Archive name collision: '+name)
        if not dest.exists():shutil.copy2(source,dest)
        reader=PdfReader(dest);pages=[]
        for index,page in enumerate(reader.pages,1):pages.append({'page':index,'text':page.extract_text() or ''})
        (output/(key+'.pages.json')).write_text(json.dumps(pages,ensure_ascii=False,indent=2),encoding='utf-8')
        (output/(key+'.txt')).write_text('\n\n'.join(f'===== PDF PAGE {p["page"]} =====\n{p["text"]}' for p in pages),encoding='utf-8')
        records.append({'id':key,'source':str(source),'archive':str(dest),'sha256':digest,'pages':len(pages),'text_characters':sum(len(p['text']) for p in pages),'text_path':str(output/(key+'.txt'))})
    (output/'paper_manifest.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps([{k:r[k] for k in ['id','pages','text_characters']} for r in records],ensure_ascii=False))


if __name__=='__main__':main()
