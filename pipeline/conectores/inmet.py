"""Conector INMET — alertas meteorológicos ativos, filtrados por UF.
Endpoint público; tratado defensivamente pois pode mudar sem aviso.
"""
import requests

URL = "https://apiprevmet3.inmet.gov.br/avisos/ativos"


def alertas_uf(uf):
    """Retorna alertas ativos que mencionam a UF. Nunca lança exceção:
    em caso de falha, devolve lista vazia com o erro registrado."""
    try:
        r = requests.get(URL, timeout=30)
        r.raise_for_status()
        avisos = r.json()
        if not isinstance(avisos, list):
            avisos = avisos.get("hoje", []) + avisos.get("futuro", []) if isinstance(avisos, dict) else []
        ativos = []
        for a in avisos:
            estados = str(a.get("estados", "") or "")
            if not uf or uf in estados:
                ativos.append({
                    "evento": a.get("descricao") or a.get("evento") or "Aviso meteorológico",
                    "severidade": a.get("severidade"),
                    "inicio": a.get("data_inicio"),
                    "fim": a.get("data_fim"),
                    "municipios": a.get("municipios"),
                })
        return {"fonte": "inmet", "ativos": ativos}
    except Exception as e:  # noqa: BLE001 — fonte externa instável por natureza
        return {"fonte": "inmet", "erro": str(e), "ativos": []}
