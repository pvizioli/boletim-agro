import os
import json, gzip, sys, datetime, numpy as np
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from produtividade import ingestao, balanco_hidrico as bh, config
from scipy.optimize import lsq_linear
MD, CAD, HOJE = '10-20', 72.0, '2026-11-26'
sys.argv=['x','raw','nasa_power',MD,str(int(CAD))]
src=open('analise.py').read().split('def cv(')[0]   # reaproveita carga + fe_tend
exec(src)
ms=sorted(set(o['mun'] for o in obs)); idx={m:i for i,m in enumerate(ms)}
_, b = fe_tend(obs, obs[:1])
lam=b[-4:]; tb=b[len(ms)]
res_log=[]
# residuo in-sample para escala de erro
pred_in,_=fe_tend(obs,obs); resid=np.log([o['y'] for o in obs])-np.log(pred_in); sd_mod=float(resid.std())
repo=json.load(open('repo_serie_pr.json'))
CHAVE=["4103602","4118402","4113700","4115200","4105508","4128104","4101408","4104808","4127700","4104303","4119905","4109401"]
saida=[]
for ib in CHAVE:
    rs={d:{'tmax':v['tmax'],'tmin':v['tmin'],'prec':v['prec'],'eto':v['eto'],'rad':None,'u2':None,'rh':None} for d,v in repo['serie'][ib].items() if d<=HOJE}
    rs,_=ingestao.completar_eto(rs, muns[ib]['lat'])
    hist=serie_de(ib)
    pl='2026-'+MD
    vals=[]
    for a in range(2012,2025):
        an={d:r for d,r in hist.items() if '%d-09-01'%a<=d<='%d-04-30'%(a+1)}
        desl={}
        for d,r in an.items():
            dd=datetime.date.fromisoformat(d)
            try: desl[dd.replace(year=dd.year+2026-a).isoformat()]=r
            except ValueError: pass
        comp=dict(desl); comp.update({d:r for d,r in rs.items()})   # observado tem prioridade
        sim=bh.simular(comp,pl,cad_mm=CAD)
        L=np.log(np.clip(np.array(bh.razoes(sim),float),config.RAZAO_MIN,1))
        vals.append(float(np.exp(b[idx[ib]]+tb*(2027-2018)+L@lam)))
    simo=bh.simular(rs,pl,cad_mm=CAD)
    hist_y=[o['y'] for o in obs if o['mun']==ib]
    v=np.array(vals)
    saida.append({'ibge':ib,'nome':muns[ib]['nome'],'p10':round(float(np.percentile(v,10)),1),'p50':round(float(np.median(v)),1),'p90':round(float(np.percentile(v,90)),1),
      'media_pam_2013_25':round(float(np.mean(hist_y)),1),'pam_2025':round(rend.get((ib,2025),float('nan'))/60,1),
      'fase1_etr_etm':simo['por_fase'][0]['razao'],'fase2_etr_etm_parcial':simo['por_fase'][1]['razao'],'dias_observados':150-simo['dias_faltantes'],
      'chuva_out_nov_mm':round(sum((rs.get(d) or {}).get('prec') or 0 for d in rs if '2026-10-01'<=d<=HOJE),0)})
json.dump({'lambdas':[round(float(x),3) for x in lam],'sd_log_residuo':round(sd_mod,3),'itens':saida},open('safra2627.json','w'),indent=1,ensure_ascii=False)
print('lambdas',np.round(lam,3),'sd',round(sd_mod,3))
for s in saida: print(s)
