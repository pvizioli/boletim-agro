# -*- coding: utf-8 -*-
"""Constantes e premissas do modelo. Tudo que e premissa esta aqui e e
reportado no JSON de saida, para auditoria."""

# Fases fenologicas adotadas na tese (ciclo tardio de 150 dias, Cap. 3.2)
#   fase 1: estabelecimento (20 d) | fase 2: vegetativo (50 d)
#   fase 3: reprodutivo (40 d)     | fase 4: maturacao (40 d)
FASES = (
    ("estabelecimento", 20),
    ("vegetativo", 50),
    ("reprodutivo", 40),
    ("maturacao", 40),
)
CICLO_DIAS = sum(d for _, d in FASES)  # 150
NOMES_FASES = tuple(n for n, _ in FASES)

# Kc da soja por dias apos emergencia, digitalizado de forma aproximada da
# Figura 3.1 da tese (Allen et al., 1996). Pontos (dia, Kc); interpolacao linear.
KC_PONTOS = (
    (1, 0.30), (10, 0.30), (28, 0.60), (46, 0.95), (73, 1.25),
    (100, 1.00), (118, 0.75), (127, 0.60), (150, 0.60),
)

# Agua disponivel (CAD) por classe do ZARC/MAPA, mm (profundidade 60 cm)
AD_CLASSES = {"AD1": 24.0, "AD2": 32.0, "AD3": 42.0,
              "AD4": 55.0, "AD5": 72.0, "AD6": 95.0}
AD_PADRAO = "AD3"

# Fracao de agua disponivel que a planta extrai sem estresse (FAO-56, soja)
P_DEPLECAO = 0.5

# Pre-calibracao generica (FAO-33, Doorenbos & Kassam, 1979): Ky da soja
# ~0,85 para o ciclo; usado como lambda uniforme quando NAO ha calibracao.
# Rotulado como prior generico e com confianca baixa.
KY_PRIOR = 0.85

# Piso para a razao ETR/ETm no log (evita log(0))
RAZAO_MIN = 0.05

# Margem para considerar um dado de clima completo na janela do ciclo
LIMIAR_COBERTURA_DADOS = 0.95

# Esquema do JSON de saida
SCHEMA_SAIDA = "boletim-agro/produtividade/v1"
SACA_KG = 60.0

# Data de plantio assumida (mes-dia) por UF quando nao ha dado melhor.
# PREMISSA: substituir por ZARC/MAPA ou pelo plantio observado do proprio
# talhao/regiao. PR=1/nov segue a tese (Cap. 3.2).
PLANTIO_PADRAO_MD = {"PR": "11-01", "MT": "10-05", "GO": "10-20",
                     "MS": "10-15", "RS": "11-10", "SP": "10-25",
                     "MG": "10-25", "BA": "11-10", "TO": "10-25"}
PLANTIO_MD_FALLBACK = "10-25"
