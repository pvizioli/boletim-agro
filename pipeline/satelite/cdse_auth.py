# -*- coding: utf-8 -*-
"""Autenticação no CDSE via OAuth2 client-credentials.

Sem credenciais no ambiente, retorna None (modo dry-run do main.py).
Nunca imprime segredos.
"""

import json
import os
import urllib.parse
import urllib.request

from . import config


def credenciais_disponiveis():
    return bool(os.environ.get(config.ENV_CLIENT_ID)) and bool(
        os.environ.get(config.ENV_CLIENT_SECRET)
    )


def obter_token(timeout=30):
    """Retorna access_token (str) ou None se sem credenciais.

    Levanta exceção em falha de rede/HTTP com credenciais presentes,
    para o chamador decidir preservar a última versão válida.
    """
    if not credenciais_disponiveis():
        return None
    dados = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": os.environ[config.ENV_CLIENT_ID],
        "client_secret": os.environ[config.ENV_CLIENT_SECRET],
    }).encode("utf-8")
    req = urllib.request.Request(
        config.CDSE_TOKEN_URL,
        data=dados,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        corpo = json.load(resp)
    token = corpo.get("access_token")
    if not token:
        raise RuntimeError("CDSE respondeu sem access_token")
    return token
