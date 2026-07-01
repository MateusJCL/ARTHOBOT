# ==========================================
# CORE/ROBO.PY - Motor ATROPBOT (Playwright), modo sequencial.
# ==========================================
import os
import time
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright

import core.db as db
from core.estado import Status

PERFIL_CHROME = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Perfil_Chrome_Trizy")
PASTA_SCREENSHOTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "screenshots")
os.makedirs(PASTA_SCREENSHOTS, exist_ok=True)
CNPJ_FATURAMENTO = "38561359000100"
URL_PAINEL = "https://plataforma.trizy.com.br/#/terminal/painel"

# Quando a "Data Validade da CNH" vier vazia ou vencida, o robô a
# substitui por HOJE + este número de dias (o Trizy só exige que seja
# maior que o dia atual). Ajuste aqui se quiser outra folga.
CNH_DIAS_BUFFER = 5

# Quantas tentativas TOTAIS cada item tem antes de ficar como erro de vez.
# 2 = a tentativa normal + 1 reprocesso automático no fim da fila (assim um
# item que deu erro não fica "esquecido" enquanto o resto é agendado).
MAX_TENTATIVAS_ITEM = 2

STATUS_JA_CONCLUIDOS = ("Sucesso",)
STATUS_CTR_INVALIDO = "CTR Inválido — Fila Pausada"

# Nomes dos meses em pt-BR (o calendário do Trizy é AngularJS Material e
# mostra o rótulo do mês nesse formato, ex.: "julho 2026").
MESES_PT = [
    "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
]


class SessaoNavegador:
    def __init__(self, maquina):
        self._maquina = maquina
        self._playwright_cm = None
        self._playwright = None
        self.context = None
        self.page = None
        self._fechamento_notificado = False
        self.is_open = False  # Flag Thread-Safe para evitar o erro de cross-thread

    def _notificar_fechamento(self, *_args):
        if self._fechamento_notificado:
            return
        self._fechamento_notificado = True
        self.is_open = False
        self.context = None
        self.page = None
        
        # Só notifica a máquina se a fila ainda estava ativamente tentando agendar algo
        if self._maquina.status() not in (Status.PARADO, Status.PAUSADO_MANUAL):
            item_id = self._maquina.item_atual_id
            self._maquina.pausar_por_navegador_fechado(item_id)

    def esta_viva(self):
        """Retorna se o navegador está aberto baseado SOMENTE na flag
        `is_open` — sem tocar em nenhum objeto Playwright.

        POR QUÊ (correção do congelamento / falso 'navegador fechado' /
        página em branco ao Iniciar): o Playwright *sync* só pode ser
        usado na MESMA thread que criou o navegador (a thread do robô).
        Esta função, porém, é chamada pela thread do Flask (o polling de
        /api/robo/estado, a cada 1,5s). A versão antiga lia `self.page.url`
        aqui (mesmo que dentro de uma sub-thread) — isso é acesso
        cross-thread ao Playwright, que ora estoura exceção, ora
        'pendura'. Resultado:
          • falso 'Navegador foi fechado' (a leitura falhava/estourava o
            timeout e o código concluía 'morto' com o Chrome aberto);
          • congelamento da interface (cada poll ficava até 1,5s preso e
            podia segurar o lock interno do Playwright);
          • página em branco ao Iniciar (a trava que exige fechar o
            Chrome dependia dessa checagem furada; quando ela errava,
            o app subia um segundo Chrome no MESMO perfil já aberto,
            que carrega travado em about:blank).

        A flag `is_open` é atualizada de forma segura entre threads:
        vira True em abrir(); vira False pelo evento 'close' do Playwright
        (context/page.on('close')) e pelo robô quando uma ação estoura
        'Target closed'. Se o Chrome for morto de forma abrupta e o
        evento 'close' não disparar, use 'Fechar Navegador (forçado)'
        em Configurações para zerar o estado."""
        return bool(self.is_open) and self.page is not None

    def forcar_fechamento(self):
        """'Tirar o plugue da tomada' — usado pelo botão manual em
        Configurações para quando a detecção automática (flag de evento
        OU a checagem ativa acima) não acompanhou a realidade por
        qualquer motivo. Zera o estado incondicionalmente, sem depender
        de nenhuma resposta do navegador."""
        try:
            if self._playwright_cm is not None:
                self._playwright_cm.__exit__(None, None, None)
        except Exception:
            pass
        self.context = None
        self.page = None
        self._playwright = None
        self._playwright_cm = None
        self.is_open = False
        self._fechamento_notificado = True

    def abrir(self):
        self.fechar()
        self._fechamento_notificado = False
        self._playwright_cm = sync_playwright()
        self._playwright = self._playwright_cm.__enter__()
        self.context = self._playwright.chromium.launch_persistent_context(
            user_data_dir=PERFIL_CHROME,
            headless=False,
            args=["--disable-blink-features=AutomationControlled", "--start-maximized"],
            no_viewport=True,
        )
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        self.context.on("close", self._notificar_fechamento)
        self.page.on("close", self._notificar_fechamento)
        self.is_open = True
        return self.page

    def fechar(self):
        self._fechamento_notificado = True
        self.is_open = False
        try:
            if self.context is not None:
                self.context.close()
        except Exception:
            pass
        try:
            if self._playwright_cm is not None:
                self._playwright_cm.__exit__(None, None, None)
        except Exception:
            pass
        self.context = None
        self.page = None
        self._playwright = None
        self._playwright_cm = None

    def aguardar_fechamento_manual(self, timeout=0):
        try:
            if self.page:
                self.page.wait_for_event("close", timeout=timeout)
        except Exception:
            pass
        finally:
            self.fechar()


class RoboAtropbot:
    def __init__(self, maquina, log_bus, modo_guiado=False):
        self._maquina = maquina
        self._log_bus = log_bus
        self._maquina.modo_guiado = modo_guiado
        self._eventos_ja_capturados = set()  # evita registrar o mesmo aviso repetido nesta execução
        self._page_atual = None  # página em uso — usada pelo HUD "estilo Tesla" na tela

    def _log(self, mensagem):
        db.registrar_log_geral(mensagem)
        self._log_bus.publicar({"tipo": "log_geral", "mensagem": mensagem, "hora": time.time()})
        # Espelha o log no HUD flutuante da própria tela do Trizy (best-effort).
        if self._page_atual is not None:
            self._hud(self._page_atual, mensagem)
        item_id = self._maquina.item_atual_id
        if item_id is not None:
            db.registrar_log_item(item_id, mensagem)
            self._log_bus.publicar({"tipo": "log_item", "item_id": item_id, "mensagem": mensagem, "hora": time.time()})

    def _status_item(self, item_id, novo_status):
        db.atualizar_status_item(item_id, novo_status)
        self._log_bus.publicar({"tipo": "status_item", "item_id": item_id, "status": novo_status})

    def _checar_pausa(self):
        self._maquina.esperar_liberar()

    def _checkpoint(self, nome, descricao):
        self._checar_pausa()
        if self._maquina.cancelado:
            return
        if not self._maquina.modo_guiado:
            return
        item_id = self._maquina.item_atual_id
        self._log(f"⏵ [Guiado] {descricao} — aguardando clique em Continuar...")
        self._maquina.entrar_checkpoint_guiado(item_id, nome)
        self._log_bus.publicar({"tipo": "checkpoint", "item_id": item_id, "nome_etapa": nome})
        self._maquina.aguardar_checkpoint_guiado()
        self._checar_pausa()

    def _tentar_autopreencher_login(self, page):
        email, senha = db.obter_credenciais_trizy()
        if not email or not senha:
            self._log("Nenhuma credencial Trizy salva em Configurações — preencha manualmente.")
            return
        try:
            time.sleep(1.5)
            campo_email = page.get_by_placeholder("E-mail ou telefone").first
            if not campo_email.is_visible(timeout=3000):
                campo_email = page.locator(
                    "xpath=//label[contains(text(), 'E-mail ou telefone')]/following::input[1]"
                ).first
            campo_email.click(force=True)
            campo_email.fill(email)

            campo_senha = page.get_by_placeholder("Senha").first
            if not campo_senha.is_visible(timeout=3000):
                campo_senha = page.locator(
                    "xpath=//label[contains(text(), 'Senha')]/following::input[1]"
                ).first
            campo_senha.click(force=True)
            campo_senha.fill(senha)

            self._log("E-mail e senha preenchidos automaticamente.")
        except Exception:
            self._log("Não consegui localizar os campos de login para autopreencher — preencha manualmente.")

    def _detectar_erro_trizy(self, page):
        """Detecta o banner de erro que o PRÓPRIO Trizy mostra na tela
        (faixa escura no topo, ex.: 'Verifique sua conexão. Se o erro
        persistir entre em contato conosco', com botão FECHAR à direita)
        — diferente de um timeout do robô não achar um seletor, este é
        um aviso que o site ativamente exibe. Retorna o texto do banner
        se encontrado, ou None."""
        try:
            botao_fechar = page.get_by_role("button", name="FECHAR").first
            if botao_fechar.is_visible(timeout=500):
                container = botao_fechar.locator(
                    "xpath=ancestor::*[self::div or self::mat-toolbar][1]"
                ).first
                try:
                    texto = container.inner_text(timeout=500).strip()
                except Exception:
                    texto = "Aviso de erro do Trizy (texto não pôde ser lido)."
                # Remove o próprio "FECHAR" do final do texto capturado.
                texto = texto.replace("FECHAR", "").strip(" .\n")
                return texto or "Aviso de erro do Trizy detectado na tela."
        except Exception:
            pass
        return None

    # Seletores genéricos de avisos/popups que cobrem os padrões mais
    # comuns de AngularJS Material (a stack do Trizy) e de sites em
    # geral — não dependem de eu já saber o texto exato de cada erro.
    SELETORES_AVISO_GENERICO = [
        "md-toast",                          # toast nativo AngularJS Material
        ".md-toast-content",
        "mat-snack-bar-container",           # snackbar Angular moderno (se houver tela nessa stack)
        "[role='alert']",
        "[aria-live='assertive']",
        "[aria-live='polite']",
        ".swal2-popup",                      # SweetAlert (popup comum em apps de gestão)
        ".toast",
        ".alert",
        ".notification",
    ]

    def _tirar_screenshot(self, page, prefixo):
        """Salva um print da tela inteira e retorna o caminho relativo
        (para guardar no banco). Nunca lança exceção — se falhar, só
        retorna None, pois isto é um registro auxiliar, não algo que
        deve travar o fluxo principal do robô."""
        try:
            nome_arquivo = f"{prefixo}_{int(time.time() * 1000)}.png"
            caminho_completo = os.path.join(PASTA_SCREENSHOTS, nome_arquivo)
            page.screenshot(path=caminho_completo, timeout=3000)
            return nome_arquivo
        except Exception:
            return None

    def _capturar_qualquer_evento_na_tela(self, page, placa=None):
        """Varredura GENÉRICA: procura por qualquer elemento que pareça
        um aviso/popup/banner na tela, usando os seletores comuns acima
        — sem precisar saber de antemão o texto exato. Tudo que for
        encontrado e ainda não tiver sido registrado nesta execução é
        salvo em eventos_trizy (com screenshot), servindo de base real
        para depois refinar a detecção automática de erros específicos.
        Roda rápido (cada seletor tem timeout de 200ms) para não pesar
        no fluxo principal."""
        item_id = self._maquina.item_atual_id
        for seletor in self.SELETORES_AVISO_GENERICO:
            try:
                elemento = page.locator(seletor).first
                if not elemento.is_visible(timeout=200):
                    continue
                try:
                    texto = elemento.inner_text(timeout=300).strip()
                except Exception:
                    texto = "(elemento visível, texto não pôde ser lido)"
                if not texto:
                    continue

                chave = (seletor, texto)
                if chave in self._eventos_ja_capturados:
                    continue  # já vimos exatamente este aviso nesta execução — não repete
                self._eventos_ja_capturados.add(chave)

                texto_lower = texto.lower()
                if any(p in texto_lower for p in ("sucesso", "confirmado", "êxito")):
                    tipo = "sucesso"
                elif any(p in texto_lower for p in ("erro", "falha", "inválid", "indispon")):
                    tipo = "erro"
                else:
                    tipo = "desconhecido"

                screenshot = self._tirar_screenshot(page, f"evento_{tipo}")
                db.registrar_evento_trizy(tipo, texto, item_id=item_id, placa=placa, screenshot_path=screenshot)
                self._log(f"📋 [Captura de tela] ({seletor}) \"{texto[:120]}\"")
                self._log_bus.publicar({"tipo": "evento_trizy", "evento_tipo": tipo, "texto": texto})
            except Exception:
                continue

    def _detectar_cloudflare(self, page):
        try:
            if page.locator("iframe[src*='challenges.cloudflare.com']").count() > 0:
                return True
            if page.locator("iframe[title*='Cloudflare' i]").count() > 0:
                return True
            titulo = (page.title() or "").lower()
            if "just a moment" in titulo or "attention required" in titulo or "verificando" in titulo:
                return True
            corpo = page.locator("text=/verificando se a conex(ã|a)o é segura/i")
            if corpo.count() > 0:
                return True
        except Exception:
            pass
        return False

    def _esperar_login_confirmado(self, page, timeout_ms=300000):
        intervalo_checagem = 4000
        tempo_decorrido = 0
        avisou_cloudflare = False
        self._maquina.entrar_aguardando_login()

        while tempo_decorrido < timeout_ms:
            if self._maquina.cancelado:
                return False
            self._checar_pausa()
            try:
                page.wait_for_selector("text='Buscar terminais...'", state="visible", timeout=intervalo_checagem)
                self._maquina.sair_aguardando_login()
                return True
            except Exception:
                pass

            tempo_decorrido += intervalo_checagem
            if self._detectar_cloudflare(page):
                if not avisou_cloudflare:
                    self._log("Verificação de segurança (Cloudflare) detectada na tela — resolva-a manualmente para continuar.")
                    avisou_cloudflare = True
            else:
                avisou_cloudflare = False

        return False

    def _limpar_painel_apos_erro(self, page, placa):
        self._log(f"[{placa}] Limpando o painel...")
        try:
            page.keyboard.press("Escape")
            time.sleep(0.5)
            page.keyboard.press("Escape")
            page.reload(wait_until="domcontentloaded", timeout=15000)
            time.sleep(2)
        except Exception:
            pass

    def _achar_input_por_label(self, page, textos_label):
        """Tenta localizar um input pelo texto do rótulo (label), cobrindo
        os dois padrões que o Trizy usa: md-input-container (AngularJS
        Material) e o xpath genérico label→input seguinte. Retorna o
        Locator ou None. `textos_label` é uma lista de textos possíveis
        (ex.: variações do mesmo rótulo)."""
        for texto in textos_label:
            try:
                alvo = page.locator(f"md-input-container:has(label:has-text('{texto}')) input").first
                if alvo.count() > 0 and alvo.is_visible(timeout=800):
                    return alvo
            except Exception:
                pass
            try:
                alvo = page.locator(
                    f"xpath=//label[contains(normalize-space(.), '{texto}')]/following::input[1]"
                ).first
                if alvo.count() > 0 and alvo.is_visible(timeout=800):
                    return alvo
            except Exception:
                pass
        return None

    def _data_vencida_ou_vazia(self, valor):
        """True se o texto de data (dd/mm/aaaa) estiver vazio ou for <= hoje.
        Qualquer coisa que não dê para interpretar é tratada como 'precisa
        corrigir' (retorna True), para nunca deixar passar uma validade
        que o Trizy vá recusar."""
        valor = (valor or "").strip()
        if not valor:
            return True
        try:
            data = datetime.strptime(valor, "%d/%m/%Y").date()
        except Exception:
            return True
        return data <= datetime.now().date()

    def _selecionar_data_calendario(self, page, placa, rotulo, alvo, indice="last"):
        """ESCOLHE uma data clicando no calendário do Trizy (md-datepicker):
        clica no ícone de calendário -> navega mês a mês até o mês/ano alvo
        -> clica no dia. É assim que o Trizy registra a data de verdade
        (apenas digitar não dispara o evento Angular que habilita a Cota).

        `alvo` é um datetime.date. `indice`: 'first' = 1º datepicker da tela
        (Validade da CNH), 'last' = último (Data da seção Contrato)."""
        alvo_mes_ano = f"{MESES_PT[alvo.month - 1]} {alvo.year}"
        alvo_str = alvo.strftime("%d/%m/%Y")
        sel_mes = f"tbody.md-calendar-month:has(td.md-calendar-month-label:text-is('{alvo_mes_ano}'))"
        try:
            datepickers = page.locator("md-datepicker")
            alvo_dp = datepickers.first if indice == "first" else datepickers.last
            botao_cal = alvo_dp.locator("button").first
            self._hud(page, f"{rotulo}: abrindo o calendário…", cor="#3b82f6")
            self._destacar(page, botao_cal)
            botao_cal.click(force=True)
            time.sleep(0.9)

            # Navega até o mês/ano alvo usando as setas do calendário.
            seta_prox = page.locator(
                "button.md-calendar-next-month, button[aria-label*='Próximo' i], button[aria-label*='Next' i]"
            ).first
            seta_ant = page.locator(
                "button.md-calendar-previous-month, button[aria-label*='Anterior' i], button[aria-label*='Previous' i]"
            ).first
            seta = seta_prox if alvo >= datetime.now().date() else seta_ant

            def _mes_visivel():
                try:
                    return page.locator(sel_mes).first.is_visible(timeout=400)
                except Exception:
                    return False

            for _ in range(60):
                if _mes_visivel():
                    break
                if seta.count() > 0 and seta.is_visible():
                    seta.click(force=True)
                    time.sleep(0.12)
                else:
                    break

            # Clica no dia DENTRO do mês alvo (evita pegar o mesmo número de
            # um mês vizinho num calendário rolável).
            mes_tbody = page.locator(sel_mes).first
            escopo = mes_tbody if mes_tbody.count() > 0 else page
            dia = escopo.locator(
                "td.md-calendar-date:not(.md-calendar-date-disabled) "
                f".md-calendar-date-selection-indicator:text-is('{alvo.day}')"
            ).first
            self._destacar(page, dia)
            dia.click(force=True)
            time.sleep(0.9)
            self._log(f"[{placa}] {rotulo} escolhida no calendário: {alvo_str}.")
            return True
        except Exception as e:
            self._log(f"[{placa}] Não consegui escolher a {rotulo} no calendário: {str(e)[:140]}")
            try:
                page.keyboard.press("Escape")  # fecha um popup preso, se houver
            except Exception:
                pass
            return False

    def _preencher_validade_cnh(self, page, placa):
        """Corrige a 'Data Validade da CNH': se vier vazia ou vencida, escolhe
        no calendário HOJE + CNH_DIAS_BUFFER dias — em vez de deixar o Trizy
        exibir 'A data de validade deve ser maior que o dia atual' e pausar a
        fila. Se a data já for futura, não mexe."""
        alvo = datetime.now().date() + timedelta(days=CNH_DIAS_BUFFER)
        try:
            valor_atual = ""
            try:
                valor_atual = (page.locator("md-datepicker input").first.input_value(timeout=1000) or "").strip()
            except Exception:
                valor_atual = ""
            if not self._data_vencida_ou_vazia(valor_atual):
                self._log(f"[{placa}] Validade da CNH já é futura ({valor_atual}). Mantendo.")
                return
            self._log(
                f"[{placa}] Validade da CNH vazia/vencida ({valor_atual or 'vazia'}). "
                f"Ajustando para {alvo.strftime('%d/%m/%Y')} pelo calendário."
            )
            self._selecionar_data_calendario(page, placa, "Validade da CNH", alvo, indice="first")
        except Exception as e:
            self._log(f"[{placa}] Não consegui ajustar a Validade da CNH automaticamente: {str(e)[:120]}")

    def _preencher_data_cota(self, page, placa, data_cota):
        """Escolhe a DATA da seção 'Contrato' (a Data da Cota) no calendário
        antes de selecionar a Cota — o Trizy só habilita a Cota depois que
        essa data está preenchida ('Para selecionar uma cota, é obrigatório
        preencher a data primeiro'), e só registra de verdade quando a data é
        clicada no calendário. `data_cota` vem no formato dd/mm/aaaa."""
        data_cota = (data_cota or "").strip()
        if not data_cota:
            self._log(f"[{placa}] Sem Data da Cota definida para este item — pulando o preenchimento da data.")
            return
        try:
            alvo = datetime.strptime(data_cota, "%d/%m/%Y").date()
        except Exception:
            self._log(f"[{placa}] Data da Cota em formato inesperado ('{data_cota}') — esperado dd/mm/aaaa.")
            return
        self._selecionar_data_calendario(page, placa, "Data da Cota", alvo, indice="last")

    def _hud(self, page, texto, cor="#22c55e"):
        """Mostra/atualiza um painel flutuante NA TELA do Trizy com o passo
        atual do robô ("estilo Tesla"): dá pra acompanhar visualmente e os
        prints de erro já saem auto-explicativos. Nunca lança — é só um extra
        e a página pode estar navegando/sem contexto."""
        try:
            page.evaluate(
                """([msg, cor]) => {
                    let el = document.getElementById('atropbot-hud');
                    if (!el) {
                        el = document.createElement('div');
                        el.id = 'atropbot-hud';
                        document.body.appendChild(el);
                    }
                    el.style.cssText = 'position:fixed;z-index:2147483647;bottom:16px;right:16px;'
                        + 'max-width:380px;background:rgba(15,23,42,.93);color:#fff;padding:12px 14px;'
                        + 'border-radius:10px;font:600 13px/1.45 Inter,Segoe UI,system-ui,sans-serif;'
                        + 'box-shadow:0 8px 28px rgba(0,0,0,.4);border-left:4px solid ' + cor + ';'
                        + 'pointer-events:none;white-space:pre-wrap;';
                    el.innerHTML = '<div style="opacity:.65;font-size:10px;letter-spacing:.1em;'
                        + 'text-transform:uppercase;margin-bottom:4px">ATROPBOT</div>'
                        + String(msg).replace(/</g,'&lt;');
                }""",
                [texto, cor],
            )
        except Exception:
            pass

    def _destacar(self, page, locator):
        """Desenha um contorno vermelho temporário no elemento que o robô vai
        usar, para dar pra ver/printar o alvo de cada ação. Best-effort."""
        try:
            locator.scroll_into_view_if_needed(timeout=1500)
            locator.evaluate(
                """(el) => {
                    const anterior = el.style.outline;
                    el.style.outline = '3px solid #ef4444';
                    el.style.outlineOffset = '2px';
                    setTimeout(() => { el.style.outline = anterior; }, 1200);
                }"""
            )
        except Exception:
            pass

    def executar(self, itens_fila, sessao):
        self._log("--- INICIANDO ATROPBOT ---")
        self._maquina.iniciar_execucao()

        try:
            self._log("Abrindo novo navegador...")
            page = sessao.abrir()
            self._page_atual = page
            self._log("Acessando a plataforma...")
            page.goto(URL_PAINEL)

            try:
                page.wait_for_selector("text='Buscar terminais...'", timeout=8000)
            except Exception:
                self._log("Tela de login detectada. Tentando autopreencher e-mail e senha...")
                self._tentar_autopreencher_login(page)
                self._log("AÇÃO MANUAL: confira os dados e clique em Entrar (e resolva o Cloudflare, se aparecer).")
                self._log("O robô está pausado aguardando você entrar no painel...")
                confirmado = self._esperar_login_confirmado(page, timeout_ms=300000)
                if self._maquina.cancelado:
                    self._log("Execução cancelada durante a espera de login. Navegador permanece aberto.")
                    return
                if not confirmado:
                    self._log("ERRO: tempo esgotado aguardando o login/verificação de segurança ser concluído.")
                    self._log("Navegador permanece aberto — feche-o manualmente quando terminar.")
                    return
                self._log("Acesso confirmado! Ligando os motores...")
                time.sleep(2)

            lotes_bloqueados = set()

            # Worklist mutável: itens que derem erro recuperável são
            # RE-ENFILEIRADOS no fim (até MAX_TENTATIVAS_ITEM), para não
            # ficarem "esquecidos" enquanto o resto da fila é agendado.
            fila_trabalho = list(itens_fila)
            tentativas = {}
            _idx = 0

            while _idx < len(fila_trabalho):
                item_id, fs_destino, fazenda, contrato, placa, cpf, status, data_cota = fila_trabalho[_idx]
                _idx += 1
                self._checar_pausa()
                if self._maquina.cancelado:
                    self._log("Execução cancelada pelo usuário. Navegador permanece aberto.")
                    break
                
                if sessao.esta_viva():
                    page = sessao.page
                    self._page_atual = page
                if status in STATUS_JA_CONCLUIDOS:
                    continue

                lote_chave = (fs_destino, fazenda, contrato)
                if lote_chave in lotes_bloqueados:
                    self._log(f"[{placa}] Pulado: lote {fs_destino}/{fazenda}/{contrato} ficou retido por CTR inválido.")
                    self._status_item(item_id, STATUS_CTR_INVALIDO)
                    continue

                self._maquina.item_atual_id = item_id
                self._status_item(item_id, "Processando...")
                self._log("=========================================")
                self._log(f"[{placa}] Iniciando fluxo - Lendo dados da tabela...")

                # Verifica se o PRÓPRIO Trizy está exibindo um aviso de
                # erro na tela (ex.: instabilidade/conexão) antes de
                # tentar fazer qualquer coisa neste item — não tem
                # sentido preencher um formulário contra um site que já
                # está avisando que está com problema.
                erro_trizy = self._detectar_erro_trizy(page)
                if erro_trizy:
                    self._log(f"⚠ [{placa}] O Trizy está exibindo um aviso: \"{erro_trizy}\"")
                    self._log("⏸ Fila PAUSADA — decida se quer tentar de novo ou cancelar.")
                    self._status_item(item_id, "Aguardando...")
                    self._maquina.item_atual_id = None
                    self._maquina.pausar_por_erro_trizy(item_id, erro_trizy)
                    self._checar_pausa()
                    if self._maquina.cancelado:
                        break
                    continue

                try:
                    if "painel" not in page.url:
                        page.goto(URL_PAINEL)
                        page.wait_for_load_state("networkidle")

                    # 1. TERMINAL VALIDADOR
                    self._checar_pausa()
                    time.sleep(1)
                    header_terminal = page.locator("mat-toolbar").filter(has_text=fs_destino).first
                    if not header_terminal.is_visible(timeout=3000):
                        self._log(f"[{placa}] Terminal diferente detectado. Forçando troca para: {fs_destino}...")
                        page.goto("https://plataforma.trizy.com.br/#/terminal")
                        time.sleep(2)

                        campo_busca = page.get_by_placeholder("Buscar terminais...")
                        campo_busca.click(force=True)
                        page.keyboard.press("Control+A")
                        page.keyboard.press("Backspace")
                        campo_busca.fill(fs_destino)
                        time.sleep(1.5)

                        page.locator(f"text='{fs_destino}'").first.click(force=True)
                        time.sleep(2)
                    else:
                        self._log(f"[{placa}] Já estamos no terminal {fs_destino}. Seguindo.")

                    self._capturar_qualquer_evento_na_tela(page, placa)
                    self._checkpoint("terminal", f"Terminal {fs_destino} confirmado. Próximo passo: abrir Agendamento.")

                    page.get_by_role("button", name="AGENDAR").click()
                    page.wait_for_selector("text='Novo Agendamento'")
                    time.sleep(1)

                    # 2. CPF
                    self._checar_pausa()
                    self._log(f"[{placa}] Inserindo CPF: {cpf}...")
                    try:
                        campo_cpf = page.locator("input[aria-label*='CPF']").first
                        if not campo_cpf.is_visible():
                            campo_cpf = page.locator("md-input-container:has(label:has-text('CPF')) input").first
                        campo_cpf.fill(cpf)
                    except Exception:
                        page.locator("xpath=//label[contains(text(), 'CPF')]/following::input[1]").fill(cpf)
                    time.sleep(2)
                    self._capturar_qualquer_evento_na_tela(page, placa)
                    self._checkpoint("cpf", f"CPF {cpf} preenchido. Próximo passo: validade da CNH e composição.")

                    # 2.1 VALIDADE DA CNH (auto-correção)
                    self._checar_pausa()
                    self._preencher_validade_cnh(page, placa)
                    self._capturar_qualquer_evento_na_tela(page, placa)

                    # 3. COMPOSIÇÃO
                    self._log(f"[{placa}] Selecionando Composição via Teclado...")
                    try:
                        campo_comp = page.locator("md-select[aria-label*='Composição']").first
                        if not campo_comp.is_visible():
                            campo_comp = page.locator("md-input-container:has(label:has-text('Composição')) md-select").first

                        campo_comp.scroll_into_view_if_needed()
                        campo_comp.click(force=True)
                        time.sleep(1.5)

                        page.keyboard.type("Caminhão VUC")
                        time.sleep(1)

                        page.keyboard.press("ArrowDown")
                        time.sleep(0.2)
                        page.keyboard.press("Enter")
                    except Exception:
                        raise Exception("Sem Composição no painel.")

                    time.sleep(2)
                    self._capturar_qualquer_evento_na_tela(page, placa)
                    self._checkpoint("composicao", f"Composição selecionada. Próximo passo: cravar a placa {placa}.")

                    # 4. PLACA DA TRAÇÃO
                    self._checar_pausa()
                    self._log(f"[{placa}] Cravando a Placa correta...")
                    try:
                        campo_placa = page.locator("md-input-container:has(label:has-text('Placa da Tração')) input").first
                        if not campo_placa.is_visible():
                            campo_placa = page.locator("input[aria-label*='Placa da Tração']").first

                        campo_placa.wait_for(state="visible", timeout=4000)
                        campo_placa.scroll_into_view_if_needed()

                        campo_placa.click(force=True)
                        page.keyboard.press("Control+A")
                        page.keyboard.press("Backspace")
                        page.keyboard.type(placa, delay=100)
                    except Exception:
                        raise Exception("DOM da Placa não encontrado.")

                    # 5. COTA (CTR)
                    self._checar_pausa()
                    self._log(f"[{placa}] Cravando CTR Específico da Tabela: {contrato}...")
                    page.mouse.wheel(0, 600)
                    time.sleep(1)

                    # 5.0 DATA DA COTA — a Cota só habilita depois que a data
                    # da seção Contrato está preenchida.
                    self._preencher_data_cota(page, placa, data_cota)

                    try:
                        campo_cota = page.locator("md-input-container:has(label:has-text('Cota')) input").first
                        if not campo_cota.is_visible():
                            campo_cota = page.locator("xpath=//label[contains(text(), 'Cota')]/following::input[1]")

                        campo_cota.click(force=True)
                        page.keyboard.press("Control+A")
                        page.keyboard.press("Backspace")
                        campo_cota.press_sequentially(contrato, delay=150)
                    except Exception:
                        pass

                    try:
                        popup_cota = page.locator("text=Contrato #").filter(has_text=contrato).first
                        popup_cota.wait_for(state="visible", timeout=8000)
                        time.sleep(1.5)
                        popup_cota.click()
                    except Exception:
                        raise Exception(f"Sem CTR ({contrato}) no painel.")

                    time.sleep(1)
                    self._capturar_qualquer_evento_na_tela(page, placa)
                    self._checkpoint("ctr", f"CTR {contrato} confirmado. Próximo passo: quantidade e finalização.")

                    # 6. QUANTIDADE
                    self._checar_pausa()
                    self._log(f"[{placa}] Adicionando fração 0,01...")
                    page.mouse.wheel(0, 300)
                    time.sleep(0.5)
                    campo_qtd = page.locator("md-input-container:has(label:has-text('Quantidade')) input").first
                    if not campo_qtd.is_visible():
                        campo_qtd = page.locator("xpath=//label[contains(text(), 'Quantidade')]/following::input[1]")

                    campo_qtd.click(force=True)
                    page.keyboard.press("Control+A")
                    page.keyboard.press("Backspace")
                    campo_qtd.fill("0,01")

                    botao_add = page.get_by_role("button", name="ADICIONAR COTA").first
                    botao_add.scroll_into_view_if_needed()
                    botao_add.click(force=True)
                    time.sleep(1.5)

                    if page.locator("text='obrigatório preencher a data primeiro'").is_visible(timeout=1000):
                        raise Exception("Site Trizy bloqueou a Cota exigindo data. A data foi corrompida pela plataforma.")

                    # 7. CNPJ
                    page.mouse.wheel(0, 500)
                    time.sleep(1)
                    try:
                        campo_cnpj = page.locator("md-input-container:has(label:has-text('Documento do Transportador')) input").first
                        if not campo_cnpj.is_visible():
                            campo_cnpj = page.locator("xpath=//label[contains(text(), 'Documento do Transportador')]/following::input[1]")

                        campo_cnpj.scroll_into_view_if_needed()
                        campo_cnpj.fill(CNPJ_FATURAMENTO)
                    except Exception:
                        pass
                    time.sleep(0.5)

                    # 8. PERÍODO
                    self._log(f"[{placa}] Selecionando período...")
                    page.mouse.wheel(0, 400)
                    time.sleep(1)
                    try:
                        caixa_periodo = page.locator("md-select[aria-label*='Período']").first
                        if not caixa_periodo.is_visible():
                            caixa_periodo = page.locator("xpath=//*[contains(text(), 'Os Horários exibidos')]/following::div[1]")

                        caixa_periodo.scroll_into_view_if_needed()
                        caixa_periodo.click(force=True)
                        time.sleep(1)
                        page.keyboard.press("ArrowDown")
                        page.keyboard.press("Enter")
                    except Exception:
                        pass

                    # 9. FINALIZAÇÃO E AGENDAR
                    self._checar_pausa()
                    page.mouse.wheel(0, 1000)
                    time.sleep(1)
                    page.mouse.move(600, 500)
                    page.mouse.click(600, 500)

                    self._capturar_qualquer_evento_na_tela(page, placa)
                    self._checkpoint("agendar", f"Formulário do veículo {placa} pronto. Próximo passo: clicar em AGENDAR e confirmar.")

                    self._log(f"[{placa}] Aguardando botão AGENDAR...")
                    botao_agendar_final = page.locator("button:has-text('AGENDAR')").last
                    botao_agendar_final.scroll_into_view_if_needed()
                    self._destacar(page, botao_agendar_final)
                    botao_agendar_final.click(timeout=45000, force=True)

                    if page.locator("text='Utilize o botão ADICIONAR COTA'").is_visible(timeout=2500):
                        self._log(f"[{placa}] ALERTA TRIZY: O site pediu para clicar em Adicionar Cota novamente. Corrigindo...")
                        page.get_by_role("button", name="ADICIONAR COTA").first.click(force=True)
                        time.sleep(1.5)
                        botao_agendar_final.click(timeout=15000, force=True)

                    botao_novo_agendamento = page.get_by_role("button", name="NOVO AGENDAMENTO").first
                    botao_novo_agendamento.wait_for(state="visible", timeout=30000)

                    self._log("SUCESSO: Agendamento CONFIRMADO!")
                    screenshot_sucesso = self._tirar_screenshot(page, "sucesso")
                    db.registrar_evento_trizy("sucesso", "Agendamento confirmado.", item_id=item_id, placa=placa, screenshot_path=screenshot_sucesso)
                    self._capturar_qualquer_evento_na_tela(page, placa)
                    self._status_item(item_id, "Sucesso")
                    self._maquina.item_atual_id = None

                    botao_novo_agendamento.click()
                    time.sleep(1.5)

                except Exception as e_item:
                    erro_str = str(e_item)

                    if self._maquina.status() == Status.PAUSADO_NAVEGADOR or \
                       "Target page, context or browser has been closed" in erro_str or \
                       "Target closed" in erro_str:
                        self._log(f"🔴 [{placa}] O navegador foi fechado durante o processamento.")
                        self._log("⏸ Fila PAUSADA. Cancele ou reabra o navegador para retomar — nenhum item foi perdido.")
                        self._status_item(item_id, "Aguardando...")
                        self._maquina.item_atual_id = None
                        self._maquina.pausar_por_navegador_fechado(item_id)

                        self._checar_pausa()

                        if self._maquina.cancelado:
                            break
                        
                        # Se não foi cancelado, a thread deita o cabelo e reabre o Chrome seguro
                        if not sessao.esta_viva():
                            self._log("Reabrindo o navegador...")
                            page = sessao.abrir()
                            self._page_atual = page
                            page.goto(URL_PAINEL)
                        else:
                            page = sessao.page
                            self._page_atual = page
                        continue

                    # Registra TUDO que está na tela neste momento de
                    # erro — screenshot + qualquer aviso visível, mesmo
                    # que o robô não saiba classificar exatamente o que
                    # é. Esta é a base de dados real para depois refinar
                    # a detecção automática de erros específicos.
                    screenshot_erro = self._tirar_screenshot(page, "erro")
                    db.registrar_evento_trizy(
                        "erro", f"Exceção no robô: {erro_str[:300]}",
                        item_id=item_id, placa=placa, screenshot_path=screenshot_erro,
                    )
                    self._capturar_qualquer_evento_na_tela(page, placa)

                    # O erro acima pode ter sido CAUSADO pelo Trizy estar
                    # exibindo um aviso de erro na tela (ex.: instabilidade),
                    # que travou o seletor que o robô esperava encontrar.
                    # Checa isso antes de classificar como "Falha inesperada".
                    erro_trizy = self._detectar_erro_trizy(page)
                    if erro_trizy:
                        self._log(f"⚠ [{placa}] O Trizy exibiu um aviso durante o processamento: \"{erro_trizy}\"")
                        self._log("⏸ Fila PAUSADA — decida se quer tentar de novo ou cancelar.")
                        self._status_item(item_id, "Aguardando...")
                        self._maquina.item_atual_id = None
                        self._maquina.pausar_por_erro_trizy(item_id, erro_trizy)
                        self._checar_pausa()
                        if self._maquina.cancelado:
                            break
                        continue

                    if "Sem CTR" in erro_str:
                        self._log(f"ERRO [{placa}]: CTR {contrato} inválido/inexistente ou sem cota no Terminal.")
                        self._log(f"⛔ Fila PAUSADA: todos os itens do lote {fs_destino}/{fazenda}/{contrato} foram retidos.")
                        self._log("Use o painel de controle para decidir: tentar de novo, ou pular este lote e seguir com o restante.")
                        self._status_item(item_id, STATUS_CTR_INVALIDO)

                        self._limpar_painel_apos_erro(page, placa)

                        self._maquina.pausar_por_ctr(item_id, fs_destino, fazenda, contrato)
                        self._checar_pausa() 

                        if self._maquina.cancelado:
                            break

                        ctx = self._maquina.contexto()
                        if ctx.get("pular_lote"):
                            lotes_bloqueados.add(lote_chave)
                            self._log(f"Lote {fs_destino}/{fazenda}/{contrato} marcado para ser pulado. Seguindo com o restante da fila.")
                        else:
                            self._log(f"[{placa}] Tentando o mesmo item de novo, por decisão do usuário.")
                            self._status_item(item_id, "Aguardando...")
                        continue

                    if "Sem Composição" in erro_str:
                        self._log(f"ERRO [{placa}]: Composição não abriu.")
                        status_erro = "Erro Composição"
                    elif "A data foi corrompida" in erro_str:
                        self._log(f"ERRO [{placa}]: Trizy apagou a data. O sistema não permite confirmar cota.")
                        status_erro = "Erro Data"
                    else:
                        self._log(f"ERRO [{placa}]: Falha inesperada.")
                        status_erro = "Erro"

                    self._maquina.item_atual_id = None
                    self._limpar_painel_apos_erro(page, placa)

                    # Reprocesso automático: se ainda houver tentativa, joga
                    # o item para o FIM da fila em vez de deixá-lo esquecido.
                    tentativa_atual = tentativas.get(item_id, 1)
                    if tentativa_atual < MAX_TENTATIVAS_ITEM:
                        tentativas[item_id] = tentativa_atual + 1
                        self._log(f"↻ [{placa}] Reenfileirando para nova tentativa "
                                  f"({tentativas[item_id]}/{MAX_TENTATIVAS_ITEM}) ao fim da fila.")
                        self._status_item(item_id, "Aguardando...")
                        fila_trabalho.append(
                            (item_id, fs_destino, fazenda, contrato, placa, cpf, "Aguardando...", data_cota)
                        )
                    else:
                        self._log(f"⛔ [{placa}] Esgotou as tentativas — marcado como '{status_erro}'.")
                        self._status_item(item_id, status_erro)

            self._log("--- FILA CONCLUÍDA ---")
            self._log("O navegador permanece aberto para você conferir os agendamentos.")
            self._log("Lembre-se de FECHAR A JANELA DO CHROME antes de iniciar um novo lote.")

        except Exception as e_geral:
            if "Target page, context or browser has been closed" not in str(e_geral):
                self._log(f"ERRO: {str(e_geral)}")
        finally:
            self._maquina.finalizar()
            self._log_bus.publicar({"tipo": "finalizado"})
            # A fila terminou (ou foi cancelada), mas o Chrome fica aberto
            # para conferência. Mantemos ESTA thread viva, bloqueada no
            # evento 'close' do Playwright, até você fechar a janela.
            #
            # Isso é de propósito: como o Playwright sync só pode ser usado
            # na thread que o criou, é AQUI (e não no polling do Flask) que
            # dá para saber, sem custo e sem cross-thread, quando o Chrome
            # foi fechado — o wait_for_event('close') faz a thread continuar
            # 'pumpando' os eventos do navegador e vira a flag is_open para
            # False no instante do fechamento. Enquanto a janela estiver
            # aberta, o servidor barra um novo Iniciar (esta_viva()==True),
            # que é exatamente o comportamento desejado ("feche o Chrome
            # antes de um novo lote") — sem o risco de subir um segundo
            # Chrome no mesmo perfil e travar em about:blank.
            try:
                if sessao.is_open:
                    sessao.aguardar_fechamento_manual(timeout=0)
            except Exception:
                pass


def abrir_navegador_manual(maquina, log_bus, sessao):
    def _log(msg):
        db.registrar_log_geral(msg)
        log_bus.publicar({"tipo": "log_geral", "mensagem": msg, "hora": time.time()})

    try:
        page = sessao.abrir()
        _log("Navegador aberto manualmente. Faça login ou navegue livremente.")
        page.goto(URL_PAINEL)
        sessao.aguardar_fechamento_manual(timeout=0)
        _log("Navegador (modo manual) fechado.")
    except Exception as e:
        if "Target page, context or browser has been closed" not in str(e):
            _log(f"ERRO ao abrir navegador manual: {e}")