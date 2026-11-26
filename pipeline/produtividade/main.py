# -*- coding: utf-8 -*-
"""CLI.

  # previsao para um ponto, a partir de JSON ja baixado
  python -m produtividade.main prever --clima om.json --formato open-meteo \
      --plantio 2026-10-10 --hoje 2026-11-26 --lat -23.4 --lon -51.9 \
      --ym 65 [--modelo modelo.json] [--cad AD3]

  # lote para o boletim (precisa de rede)
  python -m produtividade.main lote --uf PR --municipios config/municipios.csv \
      --saida web/data/out/produtividade [--modelo modelo.json] [--ym 62]

  # calibracao + backtest com IBGE/PAM + Open-Meteo (precisa de rede)
  python -m produtividade.main backtest --uf PR --municipios config/municipios.csv \
      --anos 2012-2025 --saida data/produtividade
"""

import argparse
import datetime
import json
import os
import sys

from . import backtest, config, fontes, ingestao, pipeline, previsao
from .jensen import Jensen


def _ler(caminho):
    with open(caminho, encoding="utf-8") as f:
        return json.load(f)


def cmd_prever(a):
    obj = _ler(a.clima)
    conv = {"open-meteo": ingestao.de_open_meteo,
            "nasa-power": ingestao.de_nasa_power,
            "inmet": ingestao.de_inmet,
            "normalizado": lambda o: o}[a.formato]
    serie = conv(obj)
    modelo, grupos, rmse, ym = None, None, None, a.ym
    if a.modelo:
        mj = _ler(a.modelo)
        modelo = Jensen.from_dict(mj["modelo"])
        rmse = mj.get("rmse_cv_loyo_sc_ha")
        if a.ym is None and a.codigo_ibge:
            ym = (mj.get("ym_sc_ha_por_municipio") or {}).get(a.codigo_ibge)
    if ym is None:
        sys.exit("informe --ym (sc/ha potencial) ou --modelo com --codigo-ibge")
    cad = config.AD_CLASSES[a.cad]
    res = previsao.prever_safra(serie, a.plantio, a.hoje, ym, modelo=modelo,
                                cad_mm=cad, lat=a.lat, grupos=grupos,
                                rmse_modelo_sc_ha=rmse)
    res["schema"] = config.SCHEMA_SAIDA
    res["gerado_em"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    txt = json.dumps(res, ensure_ascii=False, indent=1)
    if a.saida:
        with open(a.saida, "w", encoding="utf-8") as f:
            f.write(txt)
    else:
        print(txt)


def cmd_lote(a):
    muns = backtest.carregar_municipios_csv(a.municipios, a.uf)
    mj = _ler(a.modelo) if a.modelo and os.path.exists(a.modelo) else None
    hoje = a.hoje or datetime.date.today().isoformat()
    r = pipeline.rodar_lote(muns, hoje, a.saida, mj, ym_padrao=a.ym)
    print(json.dumps({k: v for k, v in r.items() if k != "arquivos"},
                     ensure_ascii=False)[:2000])
    for c in r.get("arquivos", []):
        print("gravado:", c)
    return 0 if r["gravado"] else 1


def cmd_backtest(a):
    muns = backtest.carregar_municipios_csv(a.municipios, a.uf)
    ini, fim = [int(x) for x in a.anos.split("-")]
    anos = list(range(ini, fim + 1))
    rend = {}
    for m in muns:
        try:
            obj = fontes.baixar_json(fontes.url_sidra_pam_soja(
                m["codigo_ibge"], anos))
            rend.update(backtest.de_sidra(obj))
        except Exception as e:  # noqa: BLE001
            print("SIDRA falhou para", m["codigo_ibge"], str(e)[:100])
    obs = backtest.montar_dataset(rend, muns, backtest.obter_serie_open_meteo)
    if len(obs) < 40:
        print("dados insuficientes:", len(obs), "observacoes")
        return 1
    rel = backtest.rodar_backtest(obs)
    mod = backtest.calibrar(obs, rel)
    os.makedirs(a.saida, exist_ok=True)
    with open(os.path.join(a.saida, "backtest_relatorio.json"), "w",
              encoding="utf-8") as f:
        json.dump(rel, f, ensure_ascii=False, indent=1)
    with open(os.path.join(a.saida, "modelo_produtividade.json"), "w",
              encoding="utf-8") as f:
        json.dump(mod, f, ensure_ascii=False, indent=1)
    print(json.dumps(rel["cv"], indent=1), rel["modelo_escolhido"])
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="produtividade")
    sp = p.add_subparsers(dest="cmd", required=True)
    a = sp.add_parser("prever")
    a.add_argument("--clima", required=True)
    a.add_argument("--formato", default="open-meteo",
                   choices=["open-meteo", "nasa-power", "inmet", "normalizado"])
    a.add_argument("--plantio", required=True)
    a.add_argument("--hoje", required=True)
    a.add_argument("--lat", type=float, required=True)
    a.add_argument("--lon", type=float)
    a.add_argument("--ym", type=float)
    a.add_argument("--cad", default=config.AD_PADRAO,
                   choices=sorted(config.AD_CLASSES))
    a.add_argument("--modelo")
    a.add_argument("--codigo-ibge", dest="codigo_ibge")
    a.add_argument("--saida")
    b = sp.add_parser("lote")
    b.add_argument("--uf", required=True)
    b.add_argument("--municipios", required=True)
    b.add_argument("--saida", required=True)
    b.add_argument("--modelo")
    b.add_argument("--ym", type=float)
    b.add_argument("--hoje")
    c = sp.add_parser("backtest")
    c.add_argument("--uf", required=True)
    c.add_argument("--municipios", required=True)
    c.add_argument("--anos", default="2012-2025")
    c.add_argument("--saida", required=True)
    args = p.parse_args(argv)
    if args.cmd == "prever":
        return cmd_prever(args) or 0
    if args.cmd == "lote":
        return cmd_lote(args)
    return cmd_backtest(args)


if __name__ == "__main__":
    sys.exit(main())
