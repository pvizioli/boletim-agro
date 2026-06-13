"""Pipeline principal — lê os YAMLs de config/distritos, coleta dados das
fontes e grava data/out/{distrito}/latest.json + snapshot diário em historico/.

Uso: python pipeline/main.py
"""
import datetime
import json
import os
import sys

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from conectores import inmet, open_meteo  # noqa: E402

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(BASE, "config", "distritos")
OUT_DIR = os.path.join(BASE, "data", "out")


def carregar_distritos():
    distritos = []
    for nome in sorted(os.listdir(CONFIG_DIR)):
        if nome.endswith((".yaml", ".yml")):
            with open(os.path.join(CONFIG_DIR, nome), encoding="utf-8") as fh:
                distritos.append(yaml.safe_load(fh))
    return distritos


def processar_distrito(d):
    municipios = []
    for m in d.get("municipios", []):
        clima = open_meteo.buscar(m["lat"], m["lon"])
        municipios.append({**m, "clima": clima})
    alertas = inmet.alertas_uf(d.get("uf"))
    chaves = ("id", "nome", "regional", "uf", "regiao", "cultura_principal")
    return {
        "distrito": {k: d[k] for k in chaves if k in d},
        "gerado_em": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "municipios": municipios,
        "alertas": alertas,
        "colheita": {"status": "pendente", "fonte": None, "itens": []},  # Fase 2 preenche
    }


def salvar(distrito_id, payload):
    pasta = os.path.join(OUT_DIR, distrito_id)
    os.makedirs(pasta, exist_ok=True)
    with open(os.path.join(pasta, "latest.json"), "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    hist = os.path.join(pasta, "historico")
    os.makedirs(hist, exist_ok=True)
    hoje = datetime.date.today().isoformat()
    with open(os.path.join(hist, f"{hoje}.json"), "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)


def salvar_indice(distritos):
    """Gera data/out/index.json com a árvore Regional → Distrito para o site."""
    regionais = {}
    for d in distritos:
        reg = d.get("regional") or "Sem regional"
        regionais.setdefault(reg, []).append({
            "id": d["id"],
            "nome": d.get("nome", d["id"]),
            "uf": d.get("uf"),
            "n_municipios": len(d.get("municipios", [])),
        })
    indice = {
        "gerado_em": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "regionais": [
            {"nome": nome, "distritos": sorted(ds, key=lambda x: x["nome"])}
            for nome, ds in sorted(regionais.items())
        ],
    }
    with open(os.path.join(OUT_DIR, "index.json"), "w", encoding="utf-8") as fh:
        json.dump(indice, fh, ensure_ascii=False, indent=2)


def main():
    distritos = carregar_distritos()
    if not distritos:
        print("[ERRO] nenhum distrito em config/distritos/", file=sys.stderr)
        sys.exit(1)
    erros = 0
    for d in distritos:
        did = d.get("id", "?")
        try:
            payload = processar_distrito(d)
            salvar(did, payload)
            n_alertas = len(payload["alertas"].get("ativos", []))
            print(f"[ok] {did}: {len(payload['municipios'])} municípios · {n_alertas} alerta(s) INMET")
        except Exception as e:  # noqa: BLE001
            erros += 1
            print(f"[ERRO] {did}: {e}", file=sys.stderr)
    salvar_indice(distritos)
    print(f"[indice] {len(distritos)} distrito(s) catalogado(s)")
    if erros:
        sys.exit(1)


if __name__ == "__main__":
    main()
