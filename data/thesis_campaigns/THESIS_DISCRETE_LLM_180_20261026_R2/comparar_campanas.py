"""Run from the supplementary folder; standard library only, read-only analysis."""
from pathlib import Path
import json,collections
from fractions import Fraction
P=Path(__file__).resolve().parent
old=json.loads((P/'Preliminar/matriz_180_celdas.json').read_text(encoding='utf-8-sig'))
new=json.loads((P/'matriz_180_celdas.json').read_text(encoding='utf-8-sig'))
key=lambda r:(r['case_id'],r['variant_id'],r['mode'])
a,b={key(r):r for r in old},{key(r):r for r in new}
assert len(a)==len(b)==len(old)==len(new)==180 and a.keys()==b.keys()
levels=['PASS','FAIL','REVIEW'];result=[]
for mode in ['ALL','TEXT','VOICE_CLEAN','VOICE_NOISE']:
    pairs=[(a[k],b[k]) for k in a if mode=='ALL' or k[2]==mode];n=len(pairs)
    ca=collections.Counter(x['verdict'] for x,y in pairs);cb=collections.Counter(y['verdict'] for x,y in pairs)
    matches=sum(x['verdict']==y['verdict'] for x,y in pairs)
    pe=Fraction(sum(ca[k]*cb[k] for k in levels),n*n);po=Fraction(matches,n)
    kappa=(po-pe)/(1-pe)
    result.append({'mode':mode,'n':n,'agreement_count':matches,'agreement_pct':float(100*po),'kappa_unweighted':float(kappa),
                   'matrix':[[sum(x['verdict']==i and y['verdict']==j for x,y in pairs) for j in levels] for i in levels]})
assert result[0]['agreement_count']==157
assert all(a[k]['audio_sha256']==b[k]['audio_sha256'] for k in a if k[2]!='TEXT')
print(json.dumps({'categories':levels,'matrix_rows':'preliminary','matrix_columns':'final','same_audio_files':120,'comparison':result},ensure_ascii=False,indent=2))
