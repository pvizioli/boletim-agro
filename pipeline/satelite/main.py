# -*- coding: utf-8 -*-
"""Orquestrador do piloto satélite (S1: esqueleto + dry-run).

Uso:
    python -m pipeline.satelite.main            # dry-run se sem credenciais
    python -m pipeline.satelite.main --uf MT
    python -m pipeline.satelite.main --dry-run  # força dry-run

Comportamento:
- Sem CDSE_CLIENT_ID/SECRET no ambiente: dry-run. Valida catálogo de
  alvos e schema de saída; garante que o CSV de saída existe com
  cabeçalho; NÃO escreve estimativas.
- Com credenciais (S2+): autentica e, por enquanto, apenas confirma o
  token (a coleta real entra no S2/S3).

Integridade: este módulo só escreve em colheita_satelite.csv, nunca em
colheita.csv/colheita_regional.csv. Linhas existentes jamais são
apagadas; escrita é sempre por acréscimo com deduplicação por chave
(codigo_ibge, safra, data_referencia).
"""

import argparse
import csv
import datetime
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from satelite import cdse_auth, config, mascara_soja  # noqa: E402


def garantir_saida():
    """Cria o CSV de saída com cabeçalho se não existir. Nunca trunca."""
    if os.path.exists(config.SAIDA_CSV):
        return False
    os.makedirs(os.path.dirname(config.SAIDA_CSV), exist_ok=True)
    with open(config.SAIDA_CSV, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow(config.COLUNAS_SAIDA)
    return True


def chaves_existentes():
    """Chaves já gravadas, para escrita idempotente por acréscimo."""
    if not os.path.exists(config.SAIDA_CSV):
        return set()
    with open(config.SAIDA_CSV, newline="", encoding="utf-8-sig") as f:
        return {
            (r.get("codigo_ibge", ""), r.get("safra", ""),
             r.get("data_referencia", ""))
            for r in csv.DictReader(f)
        }


def acrescentar_linhas(linhas):
    """Acrescenta linhas novas (dedup por chave). Retorna qtde gravada."""
    existentes = chaves_existentes()
    novas = [
        l for l in linhas
        if (l.get("codigo_ibge", ""), l.get("safra", ""),
            l.get("data_referencia", "")) not in existentes
    ]
    if not novas:
        return 0
    with open(config.SAIDA_CSV, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=config.COLUNAS_SAIDA)
        for l in novas:
            w.writerow({c: l.get(c, "") for c in config.COLUNAS_SAIDA})
    return len(novas)


def rodar(uf=None, forcar_dry_run=False):
    agora = datetime.datetime.now(datetime.timezone.utc).isoformat()
    uf = uf or config.UF_PILOTO
    print("== boletim-agro / satelite ==")
    print("UF alvo: " + uf + " | " + agora)

    alvos = mascara_soja.carregar_alvos(uf)
    regioes = {}
    for a in alvos:
        regioes.setdefault(a["regiao_nome"], 0)
        regioes[a["regiao_nome"]] += 1
    print("Alvos: " + str(len(alvos)) + " municipios em " +
          str(len(regioes)) + " regioes:")
    for nome, qt in sorted(regioes.items()):
        print("  - " + nome + ": " + str(qt))

    criado = garantir_saida()
    print(("Criado " if criado else "Preservado ") + config.SAIDA_CSV)

    if forcar_dry_run or not cdse_auth.credenciais_disponiveis():
        print("[dry-run] Sem credenciais CDSE ou dry-run forcado.")
        print("[dry-run] Catalogo e schema validados; nenhuma estimativa gravada.")
        return 0

    try:
        token = cdse_auth.obter_token()
    except Exception as e:
        print("[erro] Falha de autenticacao CDSE: " + str(e))
        print("[erro] Saida preservada; nada foi alterado.")
        return 1
    print("Autenticado no CDSE com sucesso (token nao exibido).")
    print("[S2 pendente] Coleta de cenas ainda nao implementada.")
    return 0


def main():
    p = argparse.ArgumentParser(description="Piloto satelite boletim-agro")
    p.add_argument("--uf", default=None, help="UF alvo (default: MT)")
    p.add_argument("--dry-run", action="store_true", help="forca dry-run")
    args = p.parse_args()
    sys.exit(rodar(uf=args.uf, forcar_dry_run=args.dry_run))


if __name__ == "__main__":
    main()
