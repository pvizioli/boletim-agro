# Teste da tese e modelo derivado - relatorio

## 1. O que a tese faz (confirmado nas paginas)

- Jensen (1968): Y/Ym = prod (ETR/ETm)^lambda_i, 4 fases (20/50/40/40 dias
  a partir de 1/nov, ciclo de 150 dias), Eq. 3.1-3.3.
- Inovacao: agrupar municipios por k-medias (tmin, tmed, tmax, chuva maxima
  e acumulada, em blocos de 5 dias, por fase) e incluir o grupo como variavel
  indicadora. Numero de grupos pelo indice d-HC (Souza, 2007).
- Dados: SIMEPAR (clima/ETR) e IAPAR (produtividade), 26 municipios do
  Parana, safras 2003 a 2007.
- Resultado: EQM do Jensen modificado menor em todos os anos; melhora de
  49,52% a 99,77% (Tabelas 4.5 e 4.6).

Verificacao aritmetica: as porcentagens da Tabela 4.6 decorrem exatamente
da Tabela 4.5 (66,41; 60,26; 99,77; 49,52; 65,83). O valor 19,52 que
aparece no OCR da Tabela 4.6 e erro de leitura: o texto e a conta dao 49,52.

## 2. Achados metodologicos (o que impede usar a tese como esta)

1. Medida dentro da amostra. Um modelo por ano, 26 observacoes, erro
   calculado nas mesmas observacoes usadas no ajuste. Nao ha validacao
   cruzada nem ano de teste.
2. Parametros demais. Com os grupos da Tabela 4.1 (ate 12 por fase), o
   modelo de 2004 tem 36 parametros para 26 observacoes (saturado); 2005
   tem 29. A propria tese relata parametros singulares.
3. Nao e preditivo. Os coeficientes de grupo valem so para os rotulos
   daquele ano, recalculados a cada safra; a tese reconhece (pag. 33-34)
   que prever safra futura e pergunta em aberto. Alem disso, os grupos
   usam clima da safra inteira, que so se conhece no fim do ciclo.
4. Lambda varia de sinal entre anos (lambda_2 > 0 em 2003, < 0 em 2007),
   sem sentido fisiologico.

## 3. Teste em dados sinteticos (a unica coisa testavel offline)

Os dados da tese (SIMEPAR/IAPAR) nao estao disponiveis aqui e o sandbox nao alcanca
as APIs. Por isso o teste usa um gerador com a mesma estrutura (26
municipios, clima diario, balanco hidrico, produtividade por Jensen com
lambda conhecido). Isso valida a implementacao e o efeito de sobreajuste;
NAO mede acuracia no mundo real.

E1 - protocolo da tese com o numero de grupos da Tabela 4.1 (melhora
in-sample do EQM, %):

| Ano  | Grupos por fase | Param. / obs. | Agrupamento real | Rotulos ALEATORIOS (media) | Tese |
|------|-----------------|---------------|------------------|----------------------------|------|
| 2003 | 3-6-4-6         | 20 / 26       | 62,1             | 72,5                       | 66,4 |
| 2004 | 12-10-5-8       | 36 / 26       | 92,8             | 100,0                      | 60,3 |
| 2005 | 10-3-10-5       | 29 / 26       | 95,6             | 99,8                       | 99,8 |
| 2006 | 6-3-3-4         | 17 / 26       | 40,2             | 51,8                       | 49,5 |
| 2007 | 3-4-7-3         | 18 / 26       | 46,3             | 65,3                       | 65,8 |

Rotulos aleatorios, sem nenhuma informacao climatica, "melhoram" o EQM na
mesma faixa que a tese reporta. Logo, a melhora de 49% a 99% e compativel
com puro sobreajuste e nao demonstra valor dos agrupamentos.

E2 - validacao cruzada (RMSE em sc/ha, media de 20 sementes, 26 municipios,
8 safras; LOYO = preve safra nova, LOMO = preve municipio sem historico):

| Cenario          | Protocolo | Media do municipio | Jensen | Jensen + grupos |
|------------------|-----------|--------------------|--------|-----------------|
| grupos sem efeito| LOYO      | 9,38               | 4,69   | 4,03            |
| grupos sem efeito| LOMO      | 9,95               | 3,50   | 4,24            |
| grupos com efeito| LOYO      | 9,33               | 4,66   | 4,01            |
| grupos com efeito| LOMO      | 9,63               | 3,38   | 3,91            |

- O balanco hidrico + Jensen reduz o erro a cerca de metade do baseline
  (media historica), em dados onde a agua de fato manda no rendimento.
- Os grupos ajudam em LOYO (20/20 sementes) mas isso ocorre IGUALMENTE no
  cenario em que os grupos nao tem efeito real. Diagnostico: com Ym global
  em vez de Ym por municipio, o ganho some (2,97 contra 2,94). Ou seja, os
  grupos estao compensando o erro de estimar Ym, nao capturando regime
  hidrico.
- Em LOMO os grupos PIORAM (melhores que o Jensen em 2/20 sementes).

E3 - recuperacao de parametros: lambda verdadeiro 0,10/0,25/0,55/0,20,
estimado 0,12/0,17/0,51/0,15 (ruido 3%, 10 safras). Implementacao correta;
fases 2 e 4 sao as menos identificaveis.

## 4. Decisao de projeto

- Modelo operacional: Jensen simples (lambda >= 0) com balanco hidrico e
  cenarios de clima; Jensen modificado so entra se vencer o simples em LOYO
  E LOMO por margem de 5% com dados reais (backtest.py, regra automatica).
- Grupos climatologicos estaveis (media de varios anos) em vez de grupos
  recalculados por safra, para permitir previsao antes do fim do ciclo.
- Todo resultado sai como estimativa, com confianca e premissas.

## 5. O que falta (e que so da para fazer com rede)

1. Backtest real: rodar o comando backtest (PAM/SIDRA + Open-Meteo,
   2012-2025) para PR e MT. E o teste que decide se a tese serve.
2. Comparar contra a media historica e contra a produtividade CONAB/IMEA.
3. Conferir os adaptadores na primeira execucao em rede real.
4. Substituir o plantio por UF por ZARC ou por plantio observado.
5. Fase satelite: emergencia por NDVI e NDVI de pico como preditores.
