"""Run beside matriz_180_celdas.json; standard-library-only, no API or PLC access."""
from pathlib import Path
import json, collections, math, statistics, random
P=Path(__file__).resolve().parent
rows=json.loads((P/'matriz_180_celdas.json').read_text(encoding='utf-8'))
expected=json.loads((P/'estadistica.json').read_text(encoding='utf-8'))
modes=['TEXT','VOICE_CLEAN','VOICE_NOISE']
assert len(rows)==180 and len({(r['case_id'],r['variant_id'],r['mode']) for r in rows})==180
assert all(r['parser_route']=='llm' for r in rows)
by={(r['case_id'],r['variant_id'],r['mode']):r for r in rows}
result={'modes':{},'paired':[]}
for mode in modes:
    rr=[r for r in rows if r['mode']==mode];c=collections.Counter(r['verdict'] for r in rr)
    v={'n':len(rr),**dict(c),'compiled':sum(r['compilation']=='PASS' for r in rr)}
    n=len(rr);p=c['PASS']/n;z=statistics.NormalDist().inv_cdf(.975);den=1+z*z/n
    center=(p+z*z/(2*n))/den;half=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/den
    v['wilson_95_pct']=[100*(center-half),100*(center+half)]
    assert all(math.isclose(a,b,abs_tol=1e-10) for a,b in zip(v['wilson_95_pct'],expected['modes'][mode]['wilson_95_pct']))
    for key,ek in [('PASS','pass'),('FAIL','fail'),('REVIEW','review'),('compiled','compile_pass')]:assert v[key]==expected['modes'][mode][ek]
    if mode!='TEXT':
        vals=[sum(r[k] for r in rr) for k in ['substitutions','deletions','insertions','reference_word_count']]
        v['WER']=(vals[0]+vals[1]+vals[2])/vals[3]
        assert math.isclose(v['WER'],expected['modes'][mode]['pooled_wer']['WER'])
    result['modes'][mode]=v
def quantile(seq,q):
    seq=sorted(seq);x=(len(seq)-1)*q;i=int(x)
    return seq[i]+(seq[min(i+1,len(seq)-1)]-seq[i])*(x-i)
for e in expected['paired']:
    a,b=e['first'],e['second'];ds=[]
    for i in range(1,21):
        ds.append(sum(int(by[(f'D{i:02}',f'V{j}',b)]['verdict']=='PASS')-int(by[(f'D{i:02}',f'V{j}',a)]['verdict']=='PASS') for j in range(1,4)))
    rng=random.Random(20261026)
    values=[100*sum(rng.choice(ds) for _ in range(20))/60 for _ in range(20000)]
    ci=[quantile(values,.025),quantile(values,.975)]
    assert all(math.isclose(x,y,abs_tol=1e-10) for x,y in zip(ci,e['cluster_bootstrap_95_pp']))
    result['paired'].append({'A':a,'B':b,'delta_pp':100*sum(ds)/60,'cluster_95_pp':ci})
print(json.dumps({'status':'VERIFIED','selected_cells':180,**result},ensure_ascii=False,indent=2))
