"""
Fase 3 — Resumo do analista (IA) por distrito — boletim-agro
=============================================================

Para cada distrito, monta um insumo compacto com CLIMA (latest.json, gerado
3x/dia pelo pipeline), COLHEITA (CSVs — fonte da verdade, fresca no momento
do push) e PRECO, e pede a um modelo Claude um resumo curto ANCORADO
estritamente nesses dados, cruzando clima x colheita (janela/risco).

Saida: web/data/out/<distrito>/resumo.json — arquivo proprio, em trilho
separado do latest.json (o pipeline de clima nao o sobrescreve).

Regras de dados do projeto:
  - o modelo so pode usar numeros fornecidos no insumo;
  - falha na geracao NAO apaga o resumo anterior (permanece o ultimo valido);
  - rodape sempre identifica que o texto foi gerado por IA, com modelo e data.

Uso:
  ANTHROPIC_API_KEY=... python pipeline/resumo_ia.py            # todos
  ANTHROPIC_API_KEY=... python pipeline/resumo_ia.py ijui_soja  # um distrito

stdlib apenas.
"""

import datetime
import json
import os
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from conectores import colheita_csv, colheita_regional  # noqa: E402

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(BASE, "web", "data", "out")
COLHEITA_CSV = os.path.join(BASE, "data", "colheita", "colheita.csv")
COLHEITA_REGIONAL_CSV = os.path.join(BASE, "data", "colheita",
                                     "colheita_regional.csv")
CROSSWALK_CSV = os.path.join(BASE, "config", "crosswalk_regioes.csv")

MODELO = os.environ.get("RESUMO_MODELO", "claude-sonnet-4-6")
API_URL = "https://api.anthropic.com/v1/messages"

SISTEMA = (
    "Voce e o analista agrometeorologico do Boletim de Clima & Colheita "
    "(soja, Brasil). Escreva em portugues do Brasil, tom tecnico e direto, "
    "para produtores e analistas. REGRAS INEGOCIAVEIS: use SOMENTE os dados "
    "do JSON fornecido; NUNCA invente numeros, safras, fontes ou fatos; se "
    "um dado nao existir no JSON, nao fale dele; produtividade sempre em "
    "sc/ha; ao citar um numero relevante, mencione fonte e data quando "
    "disponiveis no JSON. ANALISE CLIMATICA: leia o PADRAO da semana na "
    "serie_diaria e nos sinais_derivados — evolucao da temperatura, "
    "distribuicao e concentracao da chuva, vento e rajadas, ET0 — e "
    "descreva a dinamica em linguagem sinotica honesta (ex.: queda brusca "
    "de temperatura com chuva e virada de vento sugere passagem de sistema "
    "frontal; sequencia seca com ET0 alta indica demanda hidrica). Nomeie "
    "dias da semana a partir das datas. So caracterize geada, frente ou "
    "veranico se os sinais_derivados ou a serie sustentarem. CRUZE clima e "
    "colheita: se colheita ou plantio estiverem em andamento (entre 0 e "
    "100), avalie a chuva prevista como janela ou risco por macrorregiao; "
    "se a safra estiver encerrada (entressafra), foque na dinamica do tempo, "
    "no preco e no fechamento da safra. Responda APENAS um JSON valido, sem "
    "markdown, no formato: "
    '{"texto": "analise de ate 170 palavras", '
    '"pontos": ["ponto de atencao curto", "outro ponto"]} '
    "com 3 ou 4 pontos."
)


def _log(msg):
    print("[resumo_ia] " + msg, flush=True)


def _carrega_json(caminho):
    with open(caminho, encoding="utf-8") as fh:
        return json.load(fh)


def _resumo_clima(latest):
    """Consolida o clima dos municipios do distrito em poucos numeros."""
    chuvas, tmaxs, tmins, dias_chuva = [], [], [], 0
    for m in latest.get("municipios", []):
        c = m.get("clima") or {}
        prev = c.get("previsao_7d") or []
        if not prev:
            continue
        chuvas.append(round(sum((d.get("precip_mm") or 0) for d in prev), 1))
        tmaxs.append(max((d.get("tmax") for d in prev
                          if d.get("tmax") is not None), default=None))
        tmins.append(min((d.get("tmin") for d in prev
                          if d.get("tmin") is not None), default=None))
        dc = sum(1 for d in prev
                 if (d.get("precip_mm") or 0) >= 5
                 or (d.get("prob_chuva") or 0) >= 70)
        dias_chuva = max(dias_chuva, dc)
    tmaxs = [t for t in tmaxs if t is not None]
    tmins = [t for t in tmins if t is not None]
    alertas = [(a.get("titulo") or a.get("descricao") or "alerta")
               for a in (latest.get("alertas", {}).get("ativos") or [])][:3]
    out = {
        "municipios_monitorados": len(latest.get("municipios", [])),
        "chuva_prevista_7d_mm": ({"min": min(chuvas), "max": max(chuvas)}
                                 if chuvas else None),
        "tmax_semana_c": max(tmaxs) if tmaxs else None,
        "tmin_semana_c": min(tmins) if tmins else None,
        "dias_com_chuva_relevante_7d": dias_chuva,
        "alertas_inmet_ativos": alertas,
    }
    return out


def _serie_diaria(latest):
    """Consolida a previsao municipio a municipio em UMA serie diaria do
    distrito (extremos/maximos por dia) + sinais sinoticos derivados."""
    por_dia = {}
    for m in latest.get("municipios", []):
        for d in (m.get("clima") or {}).get("previsao_7d") or []:
            dt = d.get("data")
            if not dt:
                continue
            ag = por_dia.setdefault(dt, {"data": dt})
            def _mx(campo, valor):
                if valor is None:
                    return
                if ag.get(campo) is None or valor > ag[campo]:
                    ag[campo] = valor
            def _mn(campo, valor):
                if valor is None:
                    return
                if ag.get(campo) is None or valor < ag[campo]:
                    ag[campo] = valor
            _mx("tmax", d.get("tmax")); _mn("tmin", d.get("tmin"))
            _mx("chuva_mm", d.get("precip_mm"))
            _mx("prob_chuva", d.get("prob_chuva"))
            _mx("rajada_kmh", d.get("rajada_kmh"))
            _mx("et0_mm", d.get("et0_mm"))
            if d.get("vento_dir_graus") is not None and "vento_dir_graus" not in ag:
                ag["vento_dir_graus"] = d.get("vento_dir_graus")
    serie = [por_dia[k] for k in sorted(por_dia)][:7]

    sinais = {}
    geada = [d["data"] for d in serie
             if d.get("tmin") is not None and d["tmin"] <= 3]
    if geada:
        sinais["risco_geada_tmin_ate_3c"] = geada
    seq = melhor = 0
    for d in serie:
        if (d.get("chuva_mm") or 0) < 2:
            seq += 1
            melhor = max(melhor, seq)
        else:
            seq = 0
    sinais["maior_sequencia_dias_secos"] = melhor
    for i in range(1, len(serie)):
        a, b = serie[i - 1], serie[i]
        if a.get("tmax") is not None and b.get("tmax") is not None:
            queda = a["tmax"] - b["tmax"]
            com_chuva = (b.get("chuva_mm") or 0) >= 5
            com_vento = (b.get("rajada_kmh") or 0) >= 50
            if queda >= 6 and (com_chuva or com_vento):
                sinais.setdefault("possivel_passagem_frontal", []).append(
                    b["data"])
    et_vals = [d.get("et0_mm") for d in serie if d.get("et0_mm") is not None]
    if et_vals:
        sinais["et0_media_mm_dia"] = round(sum(et_vals) / len(et_vals), 1)
    return serie, sinais


def _resumo_colheita(latest, itens_uf, itens_reg, crosswalk):
    ufs = (latest.get("distrito") or {}).get("ufs") or []
    linhas_uf, safra = [], None
    for uf in ufs:
        it = itens_uf.get(uf)
        if not it:
            continue
        if it.get("pct_plantado") is None and it.get("pct_colhido") is None:
            continue
        safra = it.get("safra") or safra
        prod = it.get("produtividade_kg_ha")
        linhas_uf.append({
            "uf": uf, "safra": it.get("safra"),
            "pct_plantado": it.get("pct_plantado"),
            "pct_colhido": it.get("pct_colhido"),
            "produtividade_sc_ha": (round(prod / 60) if prod else None),
            "producao_t": it.get("producao_t"),
            "vs_safra_anterior_pct": it.get("var_producao_pct"),
            "condicao": it.get("condicao_lavoura"),
            "fonte": it.get("fonte"),
            "data": it.get("data_referencia"),
        })
    # macrorregioes presentes no distrito (via crosswalk dos municipios)
    macros, linhas_reg = set(), []
    for m in latest.get("municipios", []):
        cw = crosswalk.get(str(m.get("ibge") or ""))
        if cw:
            macros.add((cw["uf"], cw["regiao_id"]))
    for chave in sorted(macros):
        it = itens_reg.get(chave)
        if not it:
            continue
        if it.get("pct_plantado") is None and it.get("pct_colhido") is None:
            continue
        linhas_reg.append({
            "regiao": it.get("regiao_nome"), "uf": it.get("uf"),
            "safra": it.get("safra"),
            "pct_plantado": it.get("pct_plantado"),
            "pct_colhido": it.get("pct_colhido"),
            "fonte": it.get("fonte"), "data": it.get("data_referencia"),
        })
    return linhas_uf, linhas_reg, safra


def _chama_api(api_key, insumo):
    corpo = {
        "model": MODELO,
        "max_tokens": 900,
        "temperature": 0.3,
        "system": SISTEMA,
        "messages": [{
            "role": "user",
            "content": ("Dados do distrito (JSON):\n"
                        + json.dumps(insumo, ensure_ascii=False)
                        + "\nGere o resumo agora."),
        }],
    }
    req = urllib.request.Request(API_URL, method="POST")
    req.add_header("content-type", "application/json")
    req.add_header("x-api-key", api_key)
    req.add_header("anthropic-version", "2023-06-01")
    with urllib.request.urlopen(req, json.dumps(corpo).encode(),
                                timeout=90) as r:
        resp = json.loads(r.read().decode())
    texto = "".join(b.get("text", "") for b in resp.get("content", [])
                    if b.get("type") == "text").strip()
    if texto.startswith("```"):
        texto = texto.strip("`")
        if texto.lower().startswith("json"):
            texto = texto[4:]
    return json.loads(texto)


def gerar_para_distrito(dist_id, api_key, itens_uf, itens_reg, crosswalk):
    caminho = os.path.join(OUT_DIR, dist_id, "latest.json")
    if not os.path.isfile(caminho):
        _log(dist_id + ": sem latest.json, pulando")
        return False
    latest = _carrega_json(caminho)
    linhas_uf, linhas_reg, safra = _resumo_colheita(
        latest, itens_uf, itens_reg, crosswalk)
    ufs = (latest.get("distrito") or {}).get("ufs") or []
    serie_d, sinais_d = _serie_diaria(latest)
    insumo = {
        "distrito": (latest.get("distrito") or {}).get("nome"),
        "regional": (latest.get("distrito") or {}).get("regional"),
        "ufs": ufs,
        "data_de_hoje": datetime.date.today().isoformat(),
        "clima_7dias": _resumo_clima(latest),
        "serie_diaria": serie_d,
        "sinais_derivados": sinais_d,
        "clima_gerado_em": latest.get("gerado_em"),
        "colheita_por_uf": linhas_uf,
        "colheita_por_macrorregiao": linhas_reg,
        "safra_referencia": safra,
        "preco_saca_60kg": latest.get("preco"),
    }
    for tent in (1, 2):
        try:
            saida = _chama_api(api_key, insumo)
            texto = (saida.get("texto") or "").strip()
            pontos = [p.strip() for p in (saida.get("pontos") or [])
                      if p and p.strip()][:3]
            if not texto:
                raise ValueError("resposta sem campo texto")
            resumo = {
                "distrito_id": dist_id,
                "nome": insumo["distrito"],
                "gerado_em": datetime.datetime.now(
                    datetime.timezone.utc).isoformat(timespec="seconds"),
                "modelo": MODELO,
                "texto": texto,
                "pontos": pontos,
                "insumos_ref": {
                    "clima": latest.get("gerado_em"),
                    "colheita": max((l.get("data") or ""
                                     for l in linhas_uf + linhas_reg),
                                    default=None) or None,
                    "preco": (latest.get("preco") or {}).get("data"),
                },
            }
            destino = os.path.join(OUT_DIR, dist_id, "resumo.json")
            with open(destino, "w", encoding="utf-8") as fh:
                json.dump(resumo, fh, ensure_ascii=False, indent=1)
            _log(dist_id + ": ok (" + str(len(texto)) + " chars, "
                 + str(len(pontos)) + " pontos)")
            return True
        except (urllib.error.URLError, urllib.error.HTTPError,
                ValueError, KeyError, json.JSONDecodeError) as exc:
            _log(dist_id + ": tentativa " + str(tent) + " falhou -> "
                 + repr(exc)[:160])
            time.sleep(3)
    _log(dist_id + ": FALHOU; resumo anterior (se houver) preservado")
    return False


def main():
    api_key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
    if not api_key:
        _log("ANTHROPIC_API_KEY ausente; nada a fazer (saida 0)")
        return
    alvo = sys.argv[1].strip() if len(sys.argv) > 1 and sys.argv[1].strip() \
        else ""
    itens_uf = colheita_csv.carregar(COLHEITA_CSV)
    crosswalk = colheita_regional.carregar_crosswalk(CROSSWALK_CSV)
    itens_reg = colheita_regional.carregar_regional(COLHEITA_REGIONAL_CSV)
    todos = sorted(d for d in os.listdir(OUT_DIR)
                   if os.path.isfile(os.path.join(OUT_DIR, d, "latest.json")))
    distritos = [alvo] if alvo else todos
    _log(str(len(distritos)) + " distrito(s) | modelo " + MODELO)
    ok = 0
    for i, dist_id in enumerate(distritos):
        if gerar_para_distrito(dist_id, api_key, itens_uf, itens_reg,
                               crosswalk):
            ok += 1
        if i < len(distritos) - 1:
            time.sleep(1.2)
    _log("concluido: " + str(ok) + "/" + str(len(distritos)))


if __name__ == "__main__":
    main()
