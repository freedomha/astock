import importlib.util, json, os
from collections import defaultdict
spec = importlib.util.spec_from_file_location("ga", "research/gate-redesign/analyze.py")
ga = importlib.util.module_from_spec(spec); spec.loader.exec_module(ga)
raw = json.load(open(ga.SIGNALS, encoding='utf-8'))
kl = json.load(open(ga.KLINES, encoding='utf-8'))
ser = {}
for c, bars in kl.items():
    cl, dt = ga.build_series(bars)
    ser[c] = (cl, {d: i for i, d in enumerate(dt)})
rows = []
for s in raw['signals']:
    if s.get('fwd20d') is None: continue
    c, d = s['code'], s['date']
    cl, ix = ser.get(c, (None, None))
    if not cl: continue
    i = ix.get(d)
    if i is None: continue
    f = ga.features(cl, i)
    if not f: continue
    sc = ga.score_core(f)
    rows.append(dict(code=c, date=d, fwd=s['fwd20d'], q=ga.quarter(d), **sc))
print('rows', len(rows), 'dates', len({r['date'] for r in rows}))
def spearman(xs, ys):
    n = len(xs)
    if n < 20: return None
    def rank(v):
        s0 = sorted(range(n), key=lambda k: v[k]); r=[0]*n
        for p,k in enumerate(s0): r[k]=p
        return r
    rx, ry = rank(xs), rank(ys)
    mx, my = sum(rx)/n, sum(ry)/n
    num = sum((a-mx)*(b-my) for a,b in zip(rx,ry))
    den = (sum((a-mx)**2 for a in rx)*sum((b-my)**2 for b in ry))**0.5
    return num/den if den else None
def ic_for(g, key):
    byd = defaultdict(list)
    for r in g: byd[r['date']].append(r)
    per = [v for dt, gg in byd.items() if (v := spearman([r[key] for r in gg], [r['fwd'] for r in gg])) is not None]
    if not per: return None
    per.sort()
    return dict(mean=round(sum(per)/len(per),3), pos=round(sum(1 for x in per if x>0)/len(per)*100,1), n=len(per),
                tstat=round(sum(per)/len(per)/((sum((x-sum(per)/len(per))**2 for x in per)/(len(per)-1))**0.5/len(per)**0.5),2) if len(per)>1 and sum((x-sum(per)/len(per))**2 for x in per)>0 else None)
segs = {'全样本': rows, '剔除2025Q3': [r for r in rows if r['q']!='2025Q3'], '2025Q3': [r for r in rows if r['q']=='2025Q3'], '2026': [r for r in rows if r['date'][:4]=='2026']}
out = {}
for name, g in segs.items():
    out[name] = {k: ic_for(g, k) for k in ('trend','mom','mom_mono','risk','total')}
    out[name]['_n'] = len(g); out[name]['_dates'] = len({r['date'] for r in g})
print(json.dumps(out, ensure_ascii=False, indent=1))
import os
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'seg_ic.json')
json.dump(out, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print('written', OUT)
