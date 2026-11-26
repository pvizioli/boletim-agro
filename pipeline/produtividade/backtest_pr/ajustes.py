import sys, numpy as np
sys.argv=['x']
exec(open('analise_final.py').read().split("if __name__ == '__main__':")[0])
s2 = ler_s2(os.path.join(BT, 's2')); cal = calibrar_lag(s2)
obs = montar(s2, cal['lag'], set(range(2019, 2026)))
# media dos dois calendarios (fixo e satelite)
for o in obs:
    o['rm'] = [ (a*b) ** 0.5 for a, b in zip(o['r0'], o['rs'])]
    o['rmj'] = [ (a*b) ** 0.5 for a, b in zip(o['r0j'], o['rj'])]
V = collections.OrderedDict()
V['A clima fixo (base)'] = lambda tr, te: ajusta_prediz(tr, te, 'r0', ())
V['B clima fixo + vigor (pico)'] = lambda tr, te: ajusta_prediz(tr, te, 'r0', ('pico',))
V['C calendario combinado'] = lambda tr, te: ajusta_prediz(tr, te, 'rm', ())
V['D calendario combinado + vigor (pico)'] = lambda tr, te: ajusta_prediz(tr, te, 'rm', ('pico',))
V['E 15/jan clima fixo'] = lambda tr, te: ajusta_prediz(tr, te, 'r0j', ())
V['F 15/jan clima fixo + NDVI 15/jan'] = lambda tr, te: ajusta_prediz(tr, te, 'r0j', ('n15',))
V['G 15/jan calendario combinado'] = lambda tr, te: ajusta_prediz(tr, te, 'rmj', ())
V['H 15/jan calendario combinado + NDVI 15/jan'] = lambda tr, te: ajusta_prediz(tr, te, 'rmj', ('n15',))
res = {}
for k, fn in V.items():
    a = acerto(cv(obs, fn, 'loyo')); b = acerto(cv(obs, fn, 'lomo'))
    res[k] = {'safra_nova': a, 'municipio_novo': b}
    print('%-44s safra nova %5.1f%% (+-10%% %4.1f) agreg %5.1f%% | mun novo %5.1f%% agreg %5.1f%%' % (k, a['acerto_medio_pct'], a['dentro_10pct'], a['acerto_agregado_pct'], b['acerto_medio_pct'], b['acerto_agregado_pct']))
json.dump(res, open(os.path.join(BT, 'resultado_ajustes_s2.json'), 'w'), indent=1, ensure_ascii=False)
