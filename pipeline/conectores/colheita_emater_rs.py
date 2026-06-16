"""
Extrator do Informativo Conjuntural da Emater/RS-Ascar (soja) — boletim-agro
============================================================================

Lê o boletim semanal (PDF) e extrai, via Claude (API Anthropic), os dados de
PROGRESSO da soja no RS: % semeado, % colhido, fases, area/produtividade/producao
e notas regionais qualitativas. Devolve um dict estruturado para o pipeline
mapear no bloco `colheita` dos distritos do RS (apos validacao humana).

Roda no GitHub Actions (tem internet aberta + o secret ANTHROPIC_API_KEY).
stdlib apenas (urllib) — sem pip, sem CDN.

Granularidade real: o boletim traz o numero NO NIVEL ESTADUAL; a variacao
regional costuma ser qualitativa. Por isso o schema separa os numeros do RS
das notas_regionais (texto).

Uso:
    # extrair de um PDF ja baixado (fallback robusto / teste):
    python colheita_emater_rs.py /caminho/informativo.pdf

    # tentar descobrir+baixar o mais recente e extrair:
    python colheita_emater_rs.py --auto

Requer a variavel de ambiente ANTHROPIC_API_KEY.
"""

import base64
import json
import os
import re
import sys
import urllib.request

API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-sonnet-4-6"
ANTHROPIC_VERSION = "2023-06-01"
LISTAGEM = "https://www.emater.tche.br/site/info-agro/informativo_conjuntural.php"
UA = "boletim-agro/2.0 (+https://boletim-agro.vercel.app)"

# Schema que o modelo deve devolver (string literal, sem crase)
SCHEMA = (
    '{\n'
    '  "fonte": "Emater/RS-Ascar - Informativo Conjuntural",\n'
    '  "numero": <inteiro ou null>,\n'
    '  "data_boletim": "AAAA-MM-DD ou null",\n'
    '  "safra": "ex.: 2025/2026 ou null",\n'
    '  "cultura": "soja",\n'
    '  "estado": "RS",\n'
    '  "pct_semeado": <numero 0-100 ou null>,\n'
    '  "pct_colhido": <numero 0-100 ou null>,\n'
    '  "fases": {"floracao": <num ou null>, "enchimento_graos": <num ou null>, "maturacao": <num ou null>},\n'
    '  "area_ha": <numero ou null>,\n'
    '  "produtividade_kg_ha": <numero ou null>,\n'
    '  "producao_t": <numero ou null>,\n'
    '  "condicao_geral": "<frase curta sobre a condicao das lavouras ou null>",\n'
    '  "notas_regionais": [{"regiao": "<nome>", "nota": "<observacao qualitativa>"}],\n'
    '  "observacoes": "<resumo de 1-2 frases ou null>"\n'
    '}'
)

PROMPT = (
    "Voce e um extrator de dados agricolas. O documento em anexo e o Informativo "
    "Conjuntural da Emater/RS-Ascar. Extraia SOMENTE os dados da cultura SOJA da "
    "safra de verao mais recente citada no boletim.\n\n"
    "Responda APENAS com um objeto JSON valido (sem markdown, sem cercas, sem "
    "comentarios), exatamente neste formato:\n\n" + SCHEMA + "\n\n"
    "Regras: use null quando o dado nao estiver no boletim; numeros sem unidade e "
    "sem o sinal de porcentagem (ex.: 79 para 79%); use ponto decimal; nao invente "
    "valores. Em notas_regionais, inclua apenas observacoes que o boletim atribui a "
    "regioes especificas."
)


def _chave():
    k = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not k:
        raise RuntimeError("ANTHROPIC_API_KEY nao definida no ambiente")
    return k


def extrair_de_pdf(pdf_bytes):
    """Envia o PDF ao Claude e devolve o dict estruturado da soja no RS."""
    b64 = base64.standard_b64encode(pdf_bytes).decode("ascii")
    corpo = {
        "model": MODEL,
        "max_tokens": 2000,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "document",
                 "source": {"type": "base64", "media_type": "application/pdf", "data": b64}},
                {"type": "text", "text": PROMPT},
            ],
        }],
    }
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(corpo).encode("utf-8"),
        headers={
            "x-api-key": _chave(),
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
            "user-agent": UA,
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        dados = json.loads(resp.read().decode("utf-8"))

    # Junta os blocos de texto da resposta
    texto = ""
    for bloco in dados.get("content", []):
        if bloco.get("type") == "text":
            texto += bloco.get("text", "")
    texto = texto.strip()
    # Remove eventuais cercas de codigo
    texto = re.sub(r"^```(?:json)?", "", texto).strip()
    texto = re.sub(r"```$", "", texto).strip()
    try:
        return json.loads(texto)
    except Exception as e:
        raise RuntimeError("resposta do modelo nao e JSON valido: " + str(e)
                           + " | inicio: " + texto[:200])


def descobrir_pdf_recente():
    """Best-effort: acha a URL do PDF mais recente na pagina de listagem.

    A pagina pode mudar de estrutura ou bloquear acesso automatizado; se falhar,
    use o modo de PDF direto (extrair_de_pdf) com um arquivo baixado a mao.
    """
    req = urllib.request.Request(LISTAGEM, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as resp:
        html = resp.read().decode("utf-8", "ignore")
    # links para .pdf (relativos ou absolutos)
    achados = re.findall(r'href="([^"]+\.pdf)"', html, flags=re.I)
    if not achados:
        raise RuntimeError("nenhum link .pdf encontrado na listagem")
    url = achados[0]
    if url.startswith("/"):
        url = "https://www.emater.tche.br" + url
    elif not url.startswith("http"):
        url = "https://www.emater.tche.br/site/info-agro/" + url
    return url


def baixar(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


def coletar(pdf_path=None):
    """Orquestra: usa um PDF local se dado; senao tenta descobrir+baixar."""
    if pdf_path:
        with open(pdf_path, "rb") as fh:
            pdf = fh.read()
        print("[emater-rs] extraindo de arquivo local: " + pdf_path)
    else:
        url = descobrir_pdf_recente()
        print("[emater-rs] PDF mais recente: " + url)
        pdf = baixar(url)
    return extrair_de_pdf(pdf)


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    path = None if (arg in (None, "--auto")) else arg
    resultado = coletar(path)
    print(json.dumps(resultado, ensure_ascii=False, indent=2))
