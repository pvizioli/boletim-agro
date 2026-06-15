"""Pipeline principal — boletim-agro (schema 2.0, com escalonamento)

Fonte única: config/municipios.csv. Agrupa por distrito, coleta clima EM LOTE
por distrito (Open-Meteo) e grava data/out/{distrito_id}/latest.json + snapshot
em historico/ + data/out/index.json (árvore Regional → Distrito).

Modos de uso:
    python pipeline/main.py                 # TODOS os distritos
    python pipeline/main.py sao_gabriel_soja # apenas UM (teste)
    python pipeline/main.py 3/24             # SLOT 3 de 24 (escalonamento)

Escalonamento: com "k/n", processa só os distritos cujo índice no catálogo
satisfaz indice % n == k. Rodando o workflow de hora em hora com k = hora % n,
cada rodada toca poucos distritos (rápida) e nunca tudo num bloco só.
O index.json é SEMPRE reconstruído do CSV completo (é metadado, custo zero de
API), então nunca encolhe mesmo em rodada parcial.

Princípios: falha de fonte não derruba o boletim (clima reaproveitado como
_obsoleto; INMET vazio em falha); colheita validada não regride.
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
OUT_DIR = os.path.join(BASE, "web", "data", "out")
RETENCAO_HISTORICO_DIAS = 45   # snapshots mais antigos que isso são podados


def _slug(s):
    s = str(s).upper().strip()
    s = "".join(c for c in unicodedata.normalize("NFD", s)
                if unicodedata.category(c) != "Mn")
    s = s.lower().replace("'", " ").replace("-", " ").replace(" ", "_")
    return re.sub(r"_+", "_", s).strip("_")


def carregar_distritos():
    if not os.path.exists(CSV_PATH):
        print("[ERRO] não encontrei " + CSV_PATH, file=sys.stderr)
        sys.exit(1)
    grupos = OrderedDict()
    with open(CSV_PATH, encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            grupos.setdefault(row["distrito_id"], []).append(row)
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
        distritos.append({
            "id": did,
            "nome": linhas[0]["distrito"],
            "regional": linhas[0]["regional"],
            "codigo_regional": linhas[0]["codigo_regional"],
            "uf": Counter(ufs).most_common(1)[0][0],
            "ufs": sorted(set(ufs)),
            "cultura_principal": "soja",
            "municipios": municipios,
        })
    # ordem estável (por id) para o slot ser determinístico
    distritos.sort(key=lambda d: d["id"])
    return distritos


def ler_anterior(distrito_id):
    caminho = os.path.join(OUT_DIR, distrito_id, "latest.json")
    clima_por_ibge, colheita = {}, None
    if os.path.exists(caminho):
        try:
            with open(caminho, encoding="utf-8") as fh:
                ant = json.load(fh)
            for m in ant.get("municipios", []):
                if m.get("ibge") is not None and m.get("clima") is not None:
                    clima_por_ibge[int(m["ibge"])] = m["clima"]
            colheita = ant.get("colheita")
        except Exception as e:
            print("  [aviso] latest anterior ilegível " + distrito_id + ": " + str(e))
    return clima_por_ibge, colheita


def alertas_para_ufs(ufs, cache):
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
    municipios_out, reap, semd = [], 0, 0
    for m in d["municipios"]:
        bloco = clima_novo.get(m["ibge"])
        if bloco is None:
            antigo = clima_anterior.get(m["ibge"])
            if antigo is not None:
                bloco = dict(antigo); bloco["_obsoleto"] = True; reap += 1
            else:
                semd += 1
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
    return payload, reap, semd


def _gravar_json(caminho, obj):
    """Escrita compacta (sem indentação) para reduzir tamanho/churn no repo."""
    with open(caminho, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, separators=(",", ":"))


def _podar_historico(pasta_hist, manter_dias):
    """Remove snapshots mais antigos que manter_dias (nome AAAA-MM-DD.json)."""
    corte = datetime.date.today() - datetime.timedelta(days=manter_dias)
    if not os.path.isdir(pasta_hist):
        return 0
    removidos = 0
    for nome in os.listdir(pasta_hist):
        if not nome.endswith(".json"):
            continue
        try:
            d = datetime.date.fromisoformat(nome[:-5])
        except ValueError:
            continue
        if d < corte:
            try:
                os.remove(os.path.join(pasta_hist, nome))
                removidos += 1
            except OSError:
                pass
    return removidos


def salvar(distrito_id, payload):
    pasta = os.path.join(OUT_DIR, distrito_id)
    os.makedirs(pasta, exist_ok=True)
    _gravar_json(os.path.join(pasta, "latest.json"), payload)
    hist = os.path.join(pasta, "historico")
    os.makedirs(hist, exist_ok=True)
    hoje = datetime.date.today().isoformat()
    _gravar_json(os.path.join(hist, hoje + ".json"), payload)
    _podar_historico(hist, RETENCAO_HISTORICO_DIAS)


def salvar_indice(distritos):
    """index.json com a árvore Regional → Distrito. Sempre do catálogo completo."""
    regionais = OrderedDict()
    for d in distritos:
        reg = d.get("regional") or "Sem regional"
        regionais.setdefault(reg, {"nome": reg, "codigo": d.get("codigo_regional"),
                                   "distritos": []})
        regionais[reg]["distritos"].append({
            "id": d["id"], "nome": d.get("nome", d["id"]),
            "uf": d.get("uf"), "ufs": d.get("ufs", []),
            "n_municipios": len(d.get("municipios", [])),
        })
    lista = []
    for reg in sorted(regionais):
        regionais[reg]["distritos"].sort(key=lambda x: x["nome"])
        lista.append(regionais[reg])
    indice = {
        "gerado_em": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "total_distritos": len(distritos),
        "total_municipios": sum(len(d.get("municipios", [])) for d in distritos),
        "regionais": lista,
    }
    os.makedirs(OUT_DIR, exist_ok=True)
    _gravar_json(os.path.join(OUT_DIR, "index.json"), indice)


def selecionar(distritos, arg):
    """Decide quais distritos processar a partir do argumento de linha de comando."""
    if not arg or arg == "todos":
        return distritos, "todos"
    if "/" in arg:                              # slot "k/n"
        k, n = (int(x) for x in arg.split("/", 1))
        sel = [d for i, d in enumerate(distritos) if i % n == k]
        return sel, "slot " + str(k) + "/" + str(n)
    sel = [d for d in distritos if d["id"] == arg]  # um distrito
    if not sel:
        print("[ERRO] distrito '" + arg + "' não existe no CSV", file=sys.stderr)
        sys.exit(1)
    return sel, "distrito " + arg


def main():
    catalogo = carregar_distritos()
    arg = sys.argv[1].strip() if len(sys.argv) > 1 and sys.argv[1].strip() else ""
    selecionados, rotulo = selecionar(catalogo, arg)
    print("[selecao] " + rotulo + " -> " + str(len(selecionados)) + " distrito(s)")

    alertas_cache, erros = {}, 0
    for d in selecionados:
        try:
            payload, reap, semd = processar_distrito(d, alertas_cache)
            salvar(d["id"], payload)
            n_al = len(payload["alertas"].get("ativos", []))
            msg = "[ok] " + d["id"] + ": " + str(len(payload["municipios"])) + " mun · " + str(n_al) + " INMET"
            if reap: msg += " · " + str(reap) + " reaproveitado(s)"
            if semd: msg += " · " + str(semd) + " sem dado"
            print(msg)
        except Exception as e:
            erros += 1
            print("[ERRO] " + d["id"] + ": " + str(e), file=sys.stderr)

    salvar_indice(catalogo)   # sempre do catálogo completo — nunca encolhe
    print("[indice] " + str(len(catalogo)) + " distrito(s) catalogado(s)")
    if erros:
        sys.exit(1)


if __name__ == "__main__":
    main()
