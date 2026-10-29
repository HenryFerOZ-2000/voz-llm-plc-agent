"""Publication figures from the selected final-campaign raw records only."""
from pathlib import Path
import json, csv, hashlib, argparse
R=Path(__file__).resolve().parents[2]
parser=argparse.ArgumentParser(description='Regenerar las tres figuras experimentales del artículo desde la campaña archivada.')
parser.add_argument('--campaign',type=Path,default=R/'data/thesis_campaigns/THESIS_DISCRETE_LLM_180_20261026_R2')
parser.add_argument('--output',type=Path,default=Path('figuras_reproducidas'))
args=parser.parse_args()
BASE=args.campaign.resolve()
O=args.output.resolve()
O.mkdir(parents=True,exist_ok=True)
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.ticker import FuncFormatter
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.spines.top':False,'axes.spines.right':False,
                     'axes.labelsize':10,'xtick.labelsize':9,'ytick.labelsize':9,'savefig.dpi':260})
rows=json.loads((BASE/'matriz_180_celdas.json').read_text(encoding='utf-8'))
by={(r['case_id'],r['variant_id'],r['mode']):r for r in rows}
MODES=['TEXT','VOICE_CLEAN','VOICE_NOISE']
LABELS=['Texto','Voz limpia','Voz con ruido']
BLUE='#236a87';ORANGE='#b26b30';GRAY='#60676c'
evidence={}
def save(fig,name):
    fig.savefig(O/name,bbox_inches='tight',facecolor='white')
    plt.close(fig)
def trace(row):
    p=BASE/'trials'/row['trial_id']/'evaluation/attempt_001/oracle_trace.json'
    t=json.loads(p.read_text(encoding='utf-8'))
    evidence[row['trial_id']]={'source':str(p.relative_to(BASE)).replace('\\','/'),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'samples':len(t['samples'])}
    return t
def fmt(x,pos):return f'{x:g}'.replace('.',',')

# Keep all 60 paired observations, in fixed case/variant order, on a common scale.
clean=[by[(f'D{i:02}',f'V{j}','VOICE_CLEAN')]['wer']*100 for i in range(1,21) for j in range(1,4)]
noise=[by[(f'D{i:02}',f'V{j}','VOICE_NOISE')]['wer']*100 for i in range(1,21) for j in range(1,4)]
x=np.arange(1,61)
fig,ax=plt.subplots(figsize=(10.7,3.15))
for xx,a,b in zip(x,clean,noise):ax.plot([xx,xx],[a,b],color='#aeb6bb',lw=.9,zorder=1)
ax.scatter(x,clean,s=27,marker='o',facecolors='white',edgecolors=BLUE,lw=1.2,label='Voz limpia',zorder=3)
ax.scatter(x,noise,s=25,marker='x',color=ORANGE,lw=1.2,label='Voz con ruido',zorder=4)
ax.set_xticks(np.arange(2,61,3),[f'D{i:02}' for i in range(1,21)])
for lim in np.arange(3.5,60,3):ax.axvline(lim,color='#e8ebed',lw=.6,zorder=0)
ax.set_xlim(.2,60.8);ax.set_ylim(-1,max(clean+noise)+3)
ax.set_xlabel('Caso; dentro de cada grupo: V1, V2 y V3')
ax.set_ylabel('WER por audio (%)');ax.yaxis.set_major_formatter(FuncFormatter(fmt))
ax.grid(axis='y',color='#e3e6e8',lw=.6)
ax.legend(loc='upper left',frameon=False,ncol=2)
fig.tight_layout();save(fig,'wer_pareado.png')
with (O/'datos_figura_wer.csv').open('w',encoding='utf-8',newline='') as f:
    w=csv.writer(f);w.writerow(['case_id','variant_id','clean_WER_pct','noise_WER_pct'])
    for i,(a,b) in enumerate(zip(clean,noise)):w.writerow([f'D{i//3+1:02}',f'V{i%3+1}',a,b])

# Samples and hold-last-observation segments are distinct from actual PLC transitions.
fig,axes=plt.subplots(3,1,figsize=(10.6,5.35),sharex=True)
offsets=[3.0,1.5,0]
sig=['I_Start','I_Emergency','Q_Motor_Enable']
cols=[BLUE,ORANGE,GRAY]
for ax,mode,label in zip(axes,MODES,LABELS):
    row=by[('D05','V1',mode)];t=trace(row)
    times=np.array([s['t_ms']/1000 for s in t['samples']])
    for key,off,color in zip(sig,offsets,cols):
        values=np.array([bool(s['values'][key]) for s in t['samples']],dtype=float)*.7+off
        ax.step(times,values,where='post',color=color,lw=1)
        ax.scatter(times,values,s=7,color=color,zorder=3)
    ax.set_yticks([3.35,1.85,.35],['Arranque','Emergencia','Motor'])
    ax.set_ylim(-.2,4.05);ax.set_xlim(0,3.35)
    ax.set_title(label+' · D05–V1 · PASS',loc='left',fontsize=10,pad=5)
    ax.grid(axis='x',color='#e3e6e8',lw=.6)
    ax.tick_params(axis='y',length=0)
    ax.xaxis.set_major_formatter(FuncFormatter(fmt))
axes[-1].set_xlabel('Tiempo desde el inicio de cada evaluación (s)')
fig.tight_layout(h_pad=.85);save(fig,'d05_tres_modalidades.png')

row=by[('D07','V2','TEXT')];t=trace(row)
event=next(e for e in t['events'] if e.get('type')=='set' and e.get('id')=='step_1')
origin=event['t_ms']
times=np.array([(s['t_ms']-origin)/1000 for s in t['samples']])
fig,axes=plt.subplots(2,1,figsize=(10.6,3.9),sharex=True)
for ax,key,label,color in zip(axes,['I_Start','Q_Motor_Enable'],['Arranque','Motor'],[BLUE,ORANGE]):
    values=np.array([bool(s['values'][key]) for s in t['samples']],dtype=float)
    ax.step(times,values,where='post',color=color,lw=1.2)
    ax.scatter(times,values,s=10,color=color,zorder=3)
    ax.set_ylim(-.18,1.25);ax.set_yticks([0,1],['OFF','ON']);ax.set_ylabel(label)
    ax.axvline(3,color='#444',ls='--',lw=1)
    ax.axvline(0,color='#9ba2a7',ls=':',lw=.8)
    ax.grid(axis='x',color='#e2e6e8',lw=.6)
    ax.xaxis.set_major_formatter(FuncFormatter(fmt))
axes[0].text(3.06,.45,'Arranque nominal: 3 s',fontsize=9,color='#444')
axes[1].axvspan(0,2.7,color='#eee9e2',alpha=.7,zorder=0)
axes[1].text(1.5,-.02,'Salida exigida OFF antes de 2,7 s',ha='center',fontsize=9)
on=next((s['t_ms']-origin)/1000 for s in t['samples'] if s['id']=='step_1' and s['values']['Q_Motor_Enable'])
axes[1].annotate(f'Primera muestra ON: {on:.3f} s'.replace('.',','),xy=(on,1),xytext=(.65,.55),fontsize=9,
                 arrowprops={'arrowstyle':'->','color':'#555','lw':.8})
axes[1].set_xlim(-.55,4.85);axes[1].set_xlabel('Tiempo respecto del inicio del paso de arranque (s)')
fig.tight_layout(h_pad=.35);save(fig,'d07_traza_texto.png')
evidence[row['trial_id']]['time_origin_ms']=origin
evidence[row['trial_id']]['first_observed_motor_on_s']=on


(O/'verificacion_figuras.json').write_text(json.dumps({'campaign':'THESIS_DISCRETE_LLM_180_20261026_R2','trace_sources':evidence},ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'figures':['wer_pareado.png','d05_tres_modalidades.png','d07_traza_texto.png'],'D07_first_ON_s':on}))
