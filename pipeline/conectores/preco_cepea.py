"""
Probe + coletor do preco da soja (CEPEA/ESALQ) — boletim-agro
============================================================

Objetivo desta primeira versao: descobrir se o runner do GitHub ALCANCA o CEPEA
(como Emater/IBGE bloqueiam IPs de datacenter, isso nao e garantido) e em que
FORMATO o valor aparece no HTML, para entao escrever a extracao definitiva.

Indicadores de interesse (R$/saca de 60 kg, diarios):
  - Indicador Soja CEPEA/ESALQ Parana
  - Indicador Soja ESALQ/BM&FBOVESPA Paranagua

Uso:
  python preco_cepea.py            # tenta extrair + imprime diagnostico
  python preco_cepea.py --probe    # so diagnostico (acesso + estrutura)

stdlib apenas.
"""

import json
import re
import sys
import urllib.request

UA = "Mozilla/5.0 (compatible; boletim-agro/2.0; +https://boletim-agro.vercel.app)"
URLS = [
    "https://www.cepea.org.br/br/indicador/soja.aspx",
    "https://www.cepea.org.br/br/indicador/series/soja.aspx?id=92",
]


def baixar(url, timeout=45):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "pt-BR,pt;q=0.9",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read().decode("utf-8", "ignore")


def diagnostico(html):
    """Imprime o que ajuda a entender onde esta o valor no HTML."""
    nums = re.findall(r"\b\d{2,3},\d{2}\b", html)
    print("  tamanho HTML: " + str(len(html)) + " chars")
    print("  numeros tipo 999,99: " + str(nums[:25]))
    print("  contem 'R$': " + str("R$" in html) + " | 'Indicador': "
          + str("Indicador" in html) + " | 'Paran': " + str("Paran" in html))
    for kw in ("Indicador", "Paran", "R$", "Valor"):
        i = html.find(kw)
        if i >= 0:
            trecho = re.sub(r"\s+", " ", html[i:i + 180]).strip()
            print("  ['" + kw + "' @" + str(i) + "]: " + trecho)


def tentar_extrair(html):
    """Best-effort: pega data (dd/mm/aaaa) + valor (999,99) proximos.
    Retorna lista de pares; pode falhar se o valor vier via JS."""
    achados = []
    for m in re.finditer(r"(\d{2}/\d{2}/\d{4})\D{0,40}?(\d{2,3},\d{2})", html):
        achados.append({"data": m.group(1), "valor_rs_sc": m.group(2)})
    return achados[:8]


def main(probe=False):
    for url in URLS:
        print("== " + url)
        try:
            status, html = baixar(url)
            print("  HTTP " + str(status) + " (ACESSO OK)")
            diagnostico(html)
            if not probe:
                pares = tentar_extrair(html)
                print("  extracao best-effort (data, valor): "
                      + json.dumps(pares, ensure_ascii=False))
        except Exception as e:
            print("  FALHA DE ACESSO -> " + repr(e))
        print("")


if __name__ == "__main__":
    main(probe=("--probe" in sys.argv))
