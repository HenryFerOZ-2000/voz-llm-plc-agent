"""Regenerar los diagramas explicativos del artículo desde formas y texto nativos.

No modifica capturas rasterizadas ni contiene mediciones experimentales.
"""
from pathlib import Path
import argparse,hashlib,json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch,FancyArrowPatch
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output',type=Path,default=Path(__file__).resolve().parent/'Graficos')
OUT=parser.parse_args().output.resolve()
OUT.mkdir(parents=True,exist_ok=True)
DARK='#52616f'
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':9,'text.color':'#263442','savefig.facecolor':'white'})
fig,ax=plt.subplots(figsize=(10,4.1));ax.set_xlim(0,10);ax.set_ylim(0,4.1);ax.axis('off')
def box(x,y,w,h,text,fill='#eef3f6',size=8.5):
    ax.add_patch(FancyBboxPatch((x,y),w,h,boxstyle='round,pad=0.035,rounding_size=0.07',linewidth=.8,edgecolor='#657c8d',facecolor=fill))
    ax.text(x+w/2,y+h/2,text,ha='center',va='center',fontsize=size)
def arrow(x,y,u,v,style='-'):
    ax.add_patch(FancyArrowPatch((x,y),(u,v),arrowstyle='-|>',mutation_scale=11,linewidth=1,color='#526977',linestyle=style))
box(.08,3.1,1.35,.65,'Voz en español');box(1.8,3.1,1.2,.65,'ASR remoto')
box(.08,2.05,2,.6,'Entrada textual')
box(3.55,3.1,1.65,.65,'LLM: interpretación\nsemántica')
box(.08,.8,2.85,.9,'Mapa I/O autorizado\nSímbolos, tipos, direcciones\ny permisos',fill='#e3edf3')
box(5.85,3.1,1.4,.65,'Resolución I/O')
box(7.85,3.1,1.95,.65,'IR → SCL\ny verificación local')
box(7.85,1.7,1.95,.7,'TIA Openness\nCompilación\ny descarga')
box(5.2,1.7,1.95,.7,'PLCSIM Advanced\nEstímulos y trazas')
box(5.2,.15,4.6,.75,'Modo experimental: Oráculo del caso\nExpectativas separadas del generador',fill='#f4f0e8')
for coords in [(1.43,3.425,1.8,3.425),(3,3.425,3.55,3.425),(2.08,2.35,3.55,3.2),(5.2,3.425,5.85,3.425),
               (7.25,3.425,7.85,3.425),(8.82,3.1,8.82,2.4),(7.85,2.05,7.15,2.05),(6.15,1.7,6.15,.9)]:arrow(*coords)
ax.plot([2.93,3.15,3.15,6.55],[1.25,1.25,2.9,2.9],linestyle='--',color='#526977',linewidth=1)
arrow(6.55,2.9,6.55,3.1,style='--');arrow(4.35,2.9,4.35,3.1,style='--')
note='La interpretación se realiza exclusivamente mediante el LLM.\nEl mapa condiciona la asignación de recursos.'
ax.text(.08,.15,note,fontsize=7.4,va='bottom')

fig.savefig(OUT/'arquitectura_voz_llm_plc.png',dpi=260,bbox_inches='tight',pad_inches=.05,facecolor='white')
plt.close(fig)
# A functional diagram; only the trace above is a measured time series.
fig,ax=plt.subplots(figsize=(8.5,3.6));ax.set_xlim(0,13.8);ax.set_ylim(0,5.1);ax.axis('off')
def box(x,y,w,h,label,fill='#eef3f6',size=10):
 ax.add_patch(FancyBboxPatch((x,y),w,h,boxstyle='round,pad=0.035,rounding_size=0.07',
  facecolor=fill,edgecolor='#657c8d',linewidth=.9))
 ax.text(x+w/2,y+h/2,label,ha='center',va='center',fontsize=size)
def arrow(points):
 for (x,y),(u,v) in zip(points[:-2],points[1:-1]):
  ax.plot([x,u],[y,v],color=DARK,linewidth=1)
 ax.add_patch(FancyArrowPatch(points[-2],points[-1],arrowstyle='-|>',
  mutation_scale=11,linewidth=1,color=DARK))
box(.15,3.95,2.65,.85,'Elaboración con IA\nRevisión manual',size=9.5)
box(.15,2.05,2.65,1.05,'Oráculo del caso\nPlantilla JSON',fill='#dfeaf0')
box(.15,.15,2.65,.85,'Mapa I/O\nRoles del ensayo',size=9.5)
box(3.7,3.1,2.25,.9,'Estímulos\nEntradas',size=9.5)
box(3.7,.7,2.25,.9,'Expectativas\nEstados y\nventanas',size=9.5)
box(7.0,3.1,2.75,.9,'Programa PLC\nen simulación',size=9.5)
box(7.0,1.55,2.75,.9,'Traza adquirida\nSalidas y tiempos',size=9.5)
box(10.7,1.55,2.75,.9,'Comparación\nEsperado frente\na observado',fill='#dfeaf0',size=9.5)
box(10.7,.1,2.75,.85,'Resultado\nconductual y\ndiscrepancias',size=9.5)
arrow([(.15+1.325,3.95),(.15+1.325,3.1)])
arrow([(2.8,2.72),(3.25,2.72),(3.25,3.55),(3.7,3.55)])
arrow([(2.8,2.4),(3.25,2.4),(3.25,1.15),(3.7,1.15)])
arrow([(1.475,1.0),(1.475,2.05)])
arrow([(5.95,3.55),(7.0,3.55)])
arrow([(8.375,3.1),(8.375,2.45)])
arrow([(9.75,2.0),(10.7,2.0)])
arrow([(5.95,1.15),(10.2,1.15),(10.2,1.8),(10.7,1.8)])
arrow([(12.075,1.55),(12.075,.95)])
ax.text(8.375,4.5,'Compilación y descarga previas a la prueba',ha='center',fontsize=9)
for fmt in ('png',):
 fig.savefig(OUT/f'oracle_evaluacion_discreta.{fmt}',dpi=240,bbox_inches='tight',pad_inches=.06)
plt.close(fig)


print(json.dumps({'figures':[{'file':name,'sha256':hashlib.sha256((OUT/name).read_bytes()).hexdigest()} for name in ['arquitectura_voz_llm_plc.png','oracle_evaluacion_discreta.png']],
                  'label':'Oráculo del caso','source':'Diagramas nativos; mediciones sin cambios'},ensure_ascii=True))
