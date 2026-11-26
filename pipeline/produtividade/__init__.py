# -*- coding: utf-8 -*-
"""Modelo de previsao de produtividade de soja (Jensen modificado).

Baseado na dissertacao de mestrado (Rodrigues, J. V. B.) que propoe incluir
variaveis indicadoras de agrupamento (k-medias) no modelo de Jensen (1968).
Roda em CPU, alimentado por JSON de clima/pluviometria.
"""
__version__ = "0.1.0"
