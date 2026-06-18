"""
Enriquecimento area_soja_ha — PAM/IBGE -> config/municipios.csv
==============================================================

Preenche a coluna `area_soja_ha` (area plantada de soja, em hectares) de cada
municipio no arquivo-mae, usando a Producao Agricola Municipal (PAM) do IBGE
via API v3 "agregados" (servicodados.ibge.gov.br).

- Tabela 1612 (lavouras temporarias), variavel 109 (Area plantada), nivel N6
  (municipio), classificacao 81 (produto) categoria soja.
- O codigo da soja e DESCOBERTO nos metadados (nao chutado); fallback 2713.
- Pega o ano mais recente com valor valido por municipio (cobre buracos do
  ultimo ano). Valores especiais (-, ..., X) sao ignorados.

Roda no GitHub Actions (internet aberta alcanca o IBGE). stdlib apenas.
Uso:  python enriquecer_area_soja.py [caminho_csv]
      (default: config/municipios.csv ; sobrescreve o proprio arquivo)
"""

import csv
import json
import os
import sys
import urllib.request

BASE_AGREG = "https://servicodados.ibge.gov.br/api/v3/agregados/1612"
TABELA = "1612"
VAR_AREA_PLANTADA = "109"
CLASSIF_PRODUTO = "81"
SOJA_FALLBACK = "2713"
UA = "boletim-agro/2.0 (+https://boletim-agro.vercel.app)"
CSV_PATH = sys.argv[1] if len(sys.argv) > 1 else os.path.join("config", "municipios.csv")


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def descobrir_soja_id():
    """Acha o id da categoria 'Soja' na classificacao 81 dos metadados."""
    try:
        meta = _get(BASE_AGREG + "/metadados")
        for cl in meta.get("classificacoes", []):
            if str(cl.get("id")) == CLASSIF_PRODUTO:
                for cat in cl.get("categorias", []):
                    if "soja" in str(cat.get("nome", "")).lower():
                        cid = str(cat.get("id"))
                        print("[meta] soja = categoria " + cid + " (" + str(cat.get("nome")) + ")")
                        return cid
    except Exception as e:
        print("[meta] falha ao ler metadados (" + str(e) + "); usando fallback " + SOJA_FALLBACK)
    return SOJA_FALLBACK


def _valido(v):
    """Converte valor PAM em int de hectares, ou None se especial/invalido."""
    if v is None:
        return None
    s = str(v).strip()
    if s in ("", "-", "..", "...", "X", "x"):
        return None
    try:
        return int(round(float(s.replace(",", "."))))
    except Exception:
        return None


def buscar_areas(soja_id, periodos="-5"):
    """Retorna {codigo_ibge(str): area_ha(int)} do ano mais recente valido."""
    url = (BASE_AGREG + "/periodos/" + periodos + "/variaveis/" + VAR_AREA_PLANTADA
           + "?localidades=N6[all]&classificacao=" + CLASSIF_PRODUTO + "[" + soja_id + "]")
    dados = _get(url)
    areas = {}
    for var in dados:
        for res in var.get("resultados", []):
            for s in res.get("series", []):
                ibge = str(s.get("localidade", {}).get("id", "")).strip()
                serie = s.get("serie", {}) or {}
                # ano mais recente com valor valido
                melhor = None
                for ano in sorted(serie.keys()):
                    v = _valido(serie[ano])
                    if v is not None:
                        melhor = v  # sobrescreve -> fica o ano mais recente
                if ibge and melhor is not None:
                    areas[ibge] = melhor
    return areas


def enriquecer(csv_path, areas):
    with open(csv_path, encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        campos = reader.fieldnames
        linhas = list(reader)
    if "area_soja_ha" not in campos:
        raise RuntimeError("coluna area_soja_ha ausente em " + csv_path)

    preenchidos = faltando = 0
    faltantes = []
    for r in linhas:
        ibge = str(r.get("codigo_ibge", "")).strip()
        if ibge in areas:
            r["area_soja_ha"] = str(areas[ibge])
            preenchidos += 1
        else:
            faltando += 1
            faltantes.append(r.get("cidade", "") + "/" + r.get("uf", ""))

    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=campos)
        w.writeheader()
        w.writerows(linhas)

    print("[ok] preenchidos " + str(preenchidos) + " / " + str(len(linhas))
          + " | sem dado PAM: " + str(faltando))
    if faltantes:
        print("[sem dado] " + ", ".join(faltantes[:40])
              + (" ..." if len(faltantes) > 40 else ""))
    return preenchidos, faltando


def main():
    print("[1612/PAM] enriquecendo " + CSV_PATH)
    soja_id = descobrir_soja_id()
    areas = buscar_areas(soja_id)
    print("[pam] municipios com area de soja retornados pelo IBGE: " + str(len(areas)))
    enriquecer(CSV_PATH, areas)


if __name__ == "__main__":
    main()
