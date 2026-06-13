# Dados gerados automaticamente

Esta pasta é preenchida pelo pipeline (pipeline/main.py), executado pelo GitHub Actions. Não edite estes arquivos à mão — eles são sobrescritos a cada atualização.

Após a primeira execução do workflow "Atualizar dados", aparecerá aqui uma subpasta por distrito, por exemplo:

data/out/sao_gabriel/latest.json (dados mais recentes)
data/out/sao_gabriel/historico/ (snapshot diário)

Cada latest.json contém, por município, a previsão de 7 dias e os 7 dias observados (Open-Meteo), além dos alertas INMET vigentes para a UF.
