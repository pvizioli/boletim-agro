"""Pipeline principal — boletim-agro (schema 2.0)

Lê a fonte única config/municipios.csv (Regional, Código Regional, Distrito,
distrito_id, UF, Cidade, código IBGE, lat, lon, área soja), agrupa por
distrito, coleta o clima EM LOTE por distrito (Open-Meteo) e grava
data/out/{distrito_id}/latest.json + snapshot diário em historico/ +
data/out/index.json (árvore Regional → Distrito).

Uso:
    python pipeline/main.py                 # todos os distritos
    python pipeline/main.py sao_gabriel_soja  # apenas um (teste seguro)

Princípios respeitados:
  - Falha de fonte não derruba o boletim: lote Open-Meteo que falha reaproveita
    o clima anterior (marcado _obsoleto); INMET que falha vira lista vazia.
  - Dado não regride: o bloco colheita validado é preservado em rodada só-clima.
  - Cada métrica carrega fonte + data (vem do conector).
"""
import csv
import datetime
import json
import os
import re
import sys
import unicodedata
from collections import Counter, OrderedDict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from conectores import inmet, open_meteo  # noqa: E402

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_PATH = os.path.join(BASE, "config", "municipios.csv")
OUT_DIR = os.path.join(BASE, "data", "out")


def _slug(s):
    s = str(s).upper().strip()
    s = "".join(c for c in unicodedata.normalize("NFD", s)
                if unicodedata.category(c) != "Mn")
    s = s.lower().replace("'", " ").replace("-", " ").replace(" ", "_")
    return re.sub(r"_+", "_", s).strip("_")


def carregar_distritos():
    """Lê o CSV e devolve lista de distritos no formato esperado pelo pipeline."""
    if not os.path.exists(CSV_PATH):
        print("[ERRO] não encontrei " + CSV_PATH, file=sys.stderr)
        sys.exit(1)

    grupos = OrderedDict()
    with open(CSV_PATH, encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            did = row["distrito_id"]
            grupos.setdefault(did, []).append(row)

    distritos = []
    for did, linhas in grupos.items():
        municipios = []
        for r in linhas:
            municipios.append({
                "id": _slug(r["cidade"]),
                "nome": r["cidade"],
                "ibge": int(r["codigo_ibge"]),
                "uf": r["uf"].strip(),
                "lat": float(r["latitude"]),
                "lon": float(r["longitude"]),
                "area_soja_ha": (int(float(r["area_soja_ha"]))
                                 if r.get("area_soja_ha") else None),
            })
        ufs = [m["uf"] for m in municipios]
        uf_principal = Counter(ufs).most_common(1)[0][0]
        distritos.append({
            "id": did,
            "nome": linhas[0]["distrito"],
            "regional": linhas[0]["regional"],
            "codigo_regional": linhas[0]["codigo_regional"],
            "uf": uf_principal,
            "ufs": sorted(set(ufs)),
            "cultura_principal": "soja",
            "municipios": municipios,
        })
    return distritos


def ler_anterior(distrito_id):
    """Carrega o latest.json anterior: mapa ibge->clima e o bloco colheita.

    Serve para (a) reaproveitar clima quando o lote falhar e (b) não regredir
    a colheita validada numa rodada só-clima.
    """
    caminho = os.path.join(OUT_DIR, distrito_id, "latest.json")
    clima_por_ibge = {}
    colheita = None
    if os.path.exists(caminho):
        try:
            with open(caminho, encoding="utf-8") as fh:
                ant = json.load(fh)
            for m in ant.get("municipios", []):
                if m.get("ibge") is not None and m.get("clima") is not None:
                    clima_por_ibge[int(m["ibge"])] = m["clima"]
            colheita = ant.get("colheita")
        except Exception as e:  # arquivo corrompido não pode derrubar a rodada
            print("  [aviso] não consegui ler latest anterior de "
                  + distrito_id + ": " + str(e))
    return clima_por_ibge, colheita


def alertas_para_ufs(ufs, cache):
    """Alertas INMET para todas as UFs do distrito, com cache por UF."""
    ativos = []
    for uf in ufs:
        if uf not in cache:
            try:
                cache[uf] = inmet.alertas_uf(uf) or {"ativos": []}
            except Exception as e:
                print("  [inmet] falha UF " + uf + ": " + str(e))
                cache[uf] = {"ativos": []}
        ativos.extend(cache[uf].get("ativos", []))
    return {"ativos": ativos, "ufs": sorted(set(ufs))}


def processar_distrito(d, alertas_cache):
    clima_anterior, colheita_anterior = ler_anterior(d["id"])
    clima_novo = open_meteo.buscar_clima(d["municipios"])

    municipios_out = []
    reaproveitados = 0
    sem_dado = 0
    for m in d["municipios"]:
        bloco = clima_novo.get(m["ibge"])
        if bloco is None:
            antigo = clima_anterior.get(m["ibge"])
            if antigo is not None:
                bloco = dict(antigo)
                bloco["_obsoleto"] = True
                reaproveitados += 1
            else:
                sem_dado += 1
        municipios_out.append({**m, "clima": bloco})

    alertas = alertas_para_ufs(d["ufs"], alertas_cache)
    colheita = colheita_anterior or {"status": "pendente", "fonte": None, "itens": []}

    chaves = ("id", "nome", "regional", "codigo_regional", "uf", "ufs", "cultura_principal")
    payload = {
        "distrito": {k: d[k] for k in chaves if k in d},
        "gerado_em": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "municipios": municipios_out,
        "alertas": alertas,
        "colheita": colheita,
    }
    return payload, reaproveitados, sem_dado


def salvar(distrito_id, payload):
    pasta = os.path.join(OUT_DIR, distrito_id)
    os.makedirs(pasta, exist_ok=True)
    with open(os.path.join(pasta, "latest.json"), "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    hist = os.path.join(pasta, "historico")
    os.makedirs(hist, exist_ok=True)
    hoje = datetime.date.today().isoformat()
    with open(os.path.join(hist, hoje + ".json"), "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)


def salvar_indice(distritos):
    """data/out/index.json com a árvore Regional → Distrito para o site."""
    regionais = OrderedDict()
    for d in distritos:
        reg = d.get("regional") or "Sem regional"
        regionais.setdefault(reg, {"nome": reg, "codigo": d.get("codigo_regional"),
                                   "distritos": []})
        regionais[reg]["distritos"].append({
            "id": d["id"],
            "nome": d.get("nome", d["id"]),
            "uf": d.get("uf"),
            "ufs": d.get("ufs", []),
            "n_municipios": len(d.get("municipios", [])),
        })
    lista = []
    for reg in sorted(regionais):
        bloco = regionais[reg]
        bloco["distritos"].sort(key=lambda x: x["nome"])
        lista.append(bloco)
    indice = {
        "gerado_em": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "total_distritos": len(distritos),
        "total_municipios": sum(len(d.get("municipios", [])) for d in distritos),
        "regionais": lista,
    }
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "index.json"), "w", encoding="utf-8") as fh:
        json.dump(indice, fh, ensure_ascii=False, indent=2)


def main():
    distritos = carregar_distritos()

    # filtro opcional por distrito_id (teste seguro de um só)
    filtro = sys.argv[1].strip() if len(sys.argv) > 1 and sys.argv[1].strip() else None
    if filtro:
        distritos = [d for d in distritos if d["id"] == filtro]
        if not distritos:
            print("[ERRO] distrito '" + filtro + "' não existe no CSV", file=sys.stderr)
            sys.exit(1)
        print("[filtro] rodando apenas: " + filtro)

    alertas_cache = {}
    erros = 0
    for d in distritos:
        try:
            payload, reap, semd = processar_distrito(d, alertas_cache)
            salvar(d["id"], payload)
            n_alertas = len(payload["alertas"].get("ativos", []))
            msg = ("[ok] " + d["id"] + ": " + str(len(payload["municipios"]))
                   + " municípios · " + str(n_alertas) + " alerta(s) INMET")
            if reap:
                msg += " · " + str(reap) + " clima reaproveitado(s)"
            if semd:
                msg += " · " + str(semd) + " sem dado"
            print(msg)
        except Exception as e:  # noqa: BLE001
            erros += 1
            print("[ERRO] " + d["id"] + ": " + str(e), file=sys.stderr)

    # índice só é regravado em rodada completa (sem filtro), para não encolher
    if not filtro:
        salvar_indice(distritos)
        print("[indice] " + str(len(distritos)) + " distrito(s) catalogado(s)")

    if erros:
        sys.exit(1)


if __name__ == "__main__":
    main()
