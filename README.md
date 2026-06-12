# Boletim Agroclimático Multi-Distrito

Pipeline de dados + boletim web auto-atualizável para distritos agrícolas brasileiros.
**Fase atual: 0-1** — fundação + clima automatizado (Open-Meteo + alertas INMET).

## Como funciona

1. Cada distrito é um arquivo YAML em `config/distritos/` (municípios, coordenadas, fontes)
2. O GitHub Actions roda `pipeline/main.py` automaticamente 2x/dia (06h e 18h de Brasília)
3. O pipeline consulta as APIs públicas e grava `data/out/{distrito}/latest.json` + um snapshot diário em `historico/`
4. (Fase 1) O site lê esses JSONs e exibe o boletim

Tudo roda na nuvem do GitHub — **você não precisa instalar nada no seu computador**.

## Passo a passo da primeira ativação

1. **Crie uma conta no GitHub** (github.com) se ainda não tiver
2. **Crie um repositório** chamado `boletim-agro` (pode ser privado)
3. **Envie estes arquivos**: na página do repositório, "Add file → Upload files" e arraste TODO o conteúdo desta pasta (mantendo a estrutura). Commit.
   - Atenção: a pasta `.github` é oculta em alguns sistemas — confirme que ela subiu
4. **Ative o workflow**: aba **Actions** → aceite a ativação → clique em "Atualizar dados" → botão **Run workflow**
5. **Confira o resultado** (1-2 min): deve aparecer um commit novo do `boletim-bot` com o arquivo `data/out/sao_gabriel/latest.json` preenchido com previsão de 7 dias + últimos 7 dias observados para os 7 municípios, e alertas INMET do RS

Pronto: a partir daí, os dados se atualizam sozinhos 2x/dia.

## Adicionar um novo distrito

Copie `config/distritos/sao_gabriel.yaml`, ajuste id/nome/UF/municípios (com latitude e longitude) e faça commit. O próximo ciclo já o incluirá. Nenhum código precisa mudar.

## Estrutura

```
config/distritos/   ← 1 YAML por distrito (a única coisa que você edita)
pipeline/           ← coletores Python (Open-Meteo, INMET; Fase 2: Conab, Emater...)
data/out/           ← JSONs gerados automaticamente (não editar à mão)
.github/workflows/  ← agendamento da atualização
web/                ← (Fase 1) site Next.js para o Vercel
```

## Roadmap

- [x] **Fase 0** — fundação: estrutura, config por YAML, pipeline base
- [x] **Fase 1a** — clima automatizado (Open-Meteo + INMET)
- [ ] **Fase 1b** — frontend Next.js no Vercel lendo os JSONs
- [ ] **Fase 2** — colheita: Conab automática + extração assistida por IA dos boletins estaduais (Emater-RS, Epagri-SC...) com validação humana
- [ ] **Fase 3** — resumos executivos por IA (server-side, com cache)
- [ ] **Fase 4** — escala para 25-30 distritos + página de status das fontes

## Princípios de dados

- Dado **oficial** (Emater/Conab) nunca regride; **estimativas** são sempre rotuladas como tal
- Toda métrica carrega `fonte` e data de referência
- Falha de uma fonte não derruba o boletim: a última versão válida permanece, com carimbo de data
