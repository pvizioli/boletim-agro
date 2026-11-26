import sys
sys.argv=['x']
exec(open('analise_final.py').read().split("if __name__ == '__main__':")[0])
s2 = ler_s2(os.path.join(BT, 's2')); cal = calibrar_lag(s2)
obs = montar(s2, cal['lag'], set(range(2019, 2026)))
out = {}
for nome, fn in (('clima_fixo', lambda tr, te: ajusta_prediz(tr, te, 'r0', ())),
                 ('clima_fixo_vigor', lambda tr, te: ajusta_prediz(tr, te, 'r0', ('pico', 'integ')))):
    p = cv(obs, fn, 'loyo')
    a = acerto(p, 'sat'); out[nome] = a
    print(nome, 'acerto producao (area satelite) %.1f%%' % a['acerto_producao_pct'])
    for ano, v in a['por_safra'].items(): print('  ', ano, v['prod_real_mil_t'], v['prod_prev_mil_t'], round(100*(1-abs(v['prod_prev_mil_t']-v['prod_real_mil_t'])/v['prod_real_mil_t']),1))
# area por safra
for ano in range(2019, 2026):
    L = [o for o in obs if o['ano'] == ano]
    s = sum(o['area_sat'] for o in L); r = sum(o['area_pam'] for o in L)
    print('area', ano, round(r/1e3,1), round(s/1e3,1), round(100*(1-abs(s-r)/r),1), len(L))
json.dump(out, open(os.path.join(BT, 'resultado_producao.json'), 'w'), indent=1)
