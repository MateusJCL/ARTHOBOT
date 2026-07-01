# ATROPBOT

Reescrita do AUTOMATROM como interface web local. Roda 100% no seu
computador (`http://127.0.0.1:8765`) — não expõe nada pra fora; só o
robô, quando estiver agendando de fato, precisa de internet pra falar
com o Trizy.

## Por que mudar de Tkinter para isto

Os bugs que vinham se arrastando (autocomplete travando ao apagar,
página em branco ao reprocessar, demora de até 1 minuto pra perceber
que o navegador fechou) tinham a mesma raiz: Tkinter com várias
threads e variáveis soltas tentando ficar sincronizadas à mão. Esta
reescrita ataca isso de duas formas:

1. **Interface web** em vez de Tkinter — o autocomplete agora é HTML
   puro (o campo nunca é reescrito por código enquanto você digita),
   e a fila/log agora vivem no banco (sobrevivem a fechar o programa).
2. **Uma única máquina de estados central** (`core/estado.py`) — antes
   existiam 3-4 `threading.Event` soltos e flags duplicadas tentando
   concordar sobre "o que está acontecendo agora"; hoje só existe um
   lugar que sabe o estado atual, e o navegador fechando dispara uma
   pausa instantânea e visível na tela (não silenciosa).

O **motor que conversa com o Trizy** (Playwright — seletores, ordem
dos campos, esperas) é o mesmo do AUTOMATROM, mantido onde fazia
sentido — isso já foi validado em produção e reescrever do zero só
trocaria "funciona" por "vamos descobrir de novo o que quebra".

## O que tem nesta entrega

### Configurações
- Cadastro de Veículos (criar, editar, excluir, importar CSV)
- Fazendas centralizadas — única fonte de verdade; a Operação só
  aceita fazenda já cadastrada aqui (autocomplete bloqueia o resto)
- Vínculo Fazenda → Contrato
- Credenciais do Trizy (autopreenchimento — confirmação de Entrar
  continua sempre manual)

### Operação
- Faixa "LOTE ATIVO" sempre visível — Terminal/Fazenda/Contrato
  **nunca** são lembrados entre sessões (zero memória de lote antigo)
- Fila persistida em banco — sobrevive a fechar o programa
- Autocomplete de Terminal (histórico) e Fazenda (restrito ao
  cadastro) sem o travamento ao apagar do app antigo
- Iniciar ATROPBOT, Reprocessar Erros, reprocessar item individual
  (clique direito na linha → escolher ação)
- Pausar / Retomar manual
- Modo Guiado (passo a passo, com checkpoint)
- Log em tempo real (Server-Sent Events, com polling de reforço) +
  log individual por veículo (duplo clique na linha)
- **Pausa automática se o navegador fechar** — a fila para na hora
  (não fica tentando agir numa página morta), avisa com uma janela
  clara, e você escolhe: reabrir e continuar (nenhum item perdido) ou
  cancelar
- **Trava de CTR inválido** — pausa todo o lote daquele
  Terminal/Fazenda/Contrato, com a mesma janela de decisão
  (tentar de novo / pular este lote) do app antigo
- "Limpar Lote" agora limpa de fato: campos do lote + fila + logs
  desta sessão (não só os 3 campos como no app antigo)
- **Múltiplos lotes na mesma fila** — não precisa mais esvaziar a fila
  pra trocar de Terminal/Fazenda/Contrato. Troque o lote no topo entre
  uma adição e outra; ao adicionar, a fila se reorganiza sozinha,
  agrupando veículos do mesmo lote (o robô troca de Terminal/CTR o
  mínimo de vezes possível). Cada lote tem uma cor de fundo na tabela
  e uma linha separadora mostrando onde a troca acontece. Pode
  reorganizar manualmente também (botão "🧩 Reorganizar por Lote"),
  útil depois de remover itens.

## Como rodar

1. Tenha Python 3 instalado.
2. Instale as dependências:
   ```
   pip install flask playwright pywebview
   playwright install chromium
   ```
3. Coloque a pasta `atropbot` em algum lugar fixo no computador.
4. Rode:
   ```
   python app.py
   ```
5. O navegador abre automaticamente em `http://127.0.0.1:8765`. Se não
   abrir, copie esse endereço e cole manualmente.
6. Para encerrar, feche a janela do terminal/prompt (ou Ctrl+C). Isso
   **não** fecha o Chrome do robô — ele continua aberto para
   conferência, como no app antigo.

O banco `atropbot.db` e a pasta `Perfil_Chrome_Trizy` são criados
automaticamente na primeira execução, na mesma pasta do app. **É um
banco novo**, separado do `frota_jcl.db` do AUTOMATROM — se quiser
migrar os cadastros antigos, me avise antes de usar isto no dia a dia.

## Estrutura dos arquivos

```
app.py              → ponto de entrada (rode este)
core/
  db.py              → banco de dados (SQLite) — veículos, fazendas,
                       contratos, credenciais, fila persistida, logs
  estado.py          → máquina de estados central (Maquina) + barramento
                       de eventos (LogBus) para o log em tempo real
  robo.py            → motor Playwright (mesmo fluxo do AUTOMATROM)
web/
  server.py          → servidor Flask (todas as rotas da API)
  templates/
    index.html       → estrutura da página (sidebar + Operação + Config)
  static/
    app.css          → visual
    app.js           → toda a lógica de tela

```

## O que ainda não foi portado

- Verificação de Cloudflare (detecção e aviso) — o robô já tem o
  método (`_detectar_cloudflare`), mas a UI ainda não destaca isso de
  forma diferente de um log comum. Posso refinar isso a pedido.
- Importação de planilha/CSV diretamente para a fila (hoje dá pra
  importar veículos para o cadastro, mas adicionar à fila ainda é
  veículo por veículo). Posso adicionar se for útil no seu fluxo.
