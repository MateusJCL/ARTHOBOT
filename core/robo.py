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

# ------------------------------------------------------------------
# "Modo Tesla": overlay injetado na própria página do Trizy. Mostra um
# cursor que se desloca até o alvo, um rastro (linha) ligando os pontos,
# um anel pulsando onde ele vai clicar e um balão de "pensamento" com a
# ação atual, além do painel de status no canto. Tudo é pointer-events:
# none (não atrapalha o robô) e vive numa camada z-index máxima.
# ------------------------------------------------------------------
TESLA_ENGINE_JS = r"""
(function () {
  if (window.__ATROPBOT) return;
  const NS = 'http://www.w3.org/2000/svg';
  const st = document.createElement('style');
  st.textContent = `
    #atropbot-layer{position:fixed;inset:0;z-index:2147483646;pointer-events:none;overflow:hidden;font-family:Inter,Segoe UI,system-ui,sans-serif}
    #atropbot-cursor{position:fixed;left:0;top:0;width:24px;height:24px;margin:-12px 0 0 -12px;border-radius:50%;
      background:radial-gradient(circle at 35% 35%,#bae6fd,#2563eb 72%);
      box-shadow:0 0 16px 5px rgba(56,189,248,.85),0 0 46px 12px rgba(37,99,235,.35);
      transition:left .6s cubic-bezier(.5,.05,.2,1),top .6s cubic-bezier(.5,.05,.2,1);will-change:left,top}
    #atropbot-cursor::after{content:'';position:absolute;inset:-9px;border-radius:50%;border:2px solid rgba(56,189,248,.6);
      animation:atrop-pulse 1.4s ease-out infinite}
    @keyframes atrop-pulse{0%{transform:scale(.55);opacity:.9}100%{transform:scale(1.9);opacity:0}}
    #atropbot-thought{position:fixed;left:0;top:0;transform:translate(18px,-40px);
      transition:left .6s cubic-bezier(.5,.05,.2,1),top .6s cubic-bezier(.5,.05,.2,1);
      background:rgba(15,23,42,.94);color:#e0f2fe;padding:6px 11px;border-radius:999px;font-size:12px;font-weight:700;
      white-space:nowrap;box-shadow:0 6px 18px rgba(0,0,0,.45);border:1px solid rgba(56,189,248,.55)}
    .atrop-ring{position:fixed;width:46px;height:46px;margin:-23px 0 0 -23px;border-radius:50%;border:3px solid #38bdf8;
      box-shadow:0 0 14px rgba(56,189,248,.9);animation:atrop-ring 1s ease-out forwards;pointer-events:none}
    @keyframes atrop-ring{0%{transform:scale(.3);opacity:1}100%{transform:scale(1.5);opacity:0}}
    .atrop-ripple{position:fixed;width:22px;height:22px;margin:-11px 0 0 -11px;border-radius:50%;background:rgba(239,68,68,.55);
      pointer-events:none;animation:atrop-ripple .6s ease-out forwards}
    @keyframes atrop-ripple{0%{transform:scale(.2);opacity:.9}100%{transform:scale(3.2);opacity:0}}
    #atropbot-hud{position:fixed;bottom:18px;right:18px;max-width:400px;background:rgba(15,23,42,.94);color:#fff;
      padding:14px 16px;border-radius:12px;font:600 13px/1.5 Inter,Segoe UI,system-ui,sans-serif;
      box-shadow:0 10px 34px rgba(0,0,0,.5);border-left:4px solid #22c55e;z-index:2147483647;pointer-events:none;white-space:pre-wrap}
    #atropbot-hud .atrop-tag{display:flex;align-items:center;gap:7px;opacity:.75;font-size:10px;letter-spacing:.14em;
      text-transform:uppercase;margin-bottom:5px}
    #atropbot-hud .atrop-dot{width:8px;height:8px;border-radius:50%;background:#22c55e;box-shadow:0 0 8px #22c55e;animation:atrop-blink 1s infinite}
    @keyframes atrop-blink{50%{opacity:.25}}
    #atropbot-console{position:fixed;top:14px;left:14px;width:430px;max-width:44vw;max-height:52vh;display:flex;flex-direction:column;
      background:rgba(2,6,23,.92);color:#e2e8f0;border-radius:12px;box-shadow:0 10px 34px rgba(0,0,0,.55);
      border:1px solid rgba(56,189,248,.35);z-index:2147483647;pointer-events:none;overflow:hidden;
      font:500 12px/1.5 'JetBrains Mono',Consolas,Menlo,monospace}
    .atrop-box{position:fixed;border:2px solid #22c55e;border-radius:4px;box-shadow:0 0 0 2px rgba(34,197,94,.25),0 0 12px rgba(34,197,94,.5);
      pointer-events:none;z-index:2147483646;transition:opacity .3s}
    .atrop-box>span{position:absolute;top:-19px;left:-2px;background:#22c55e;color:#052e16;font:700 10px/1 Inter,system-ui,sans-serif;
      padding:3px 6px;border-radius:4px 4px 4px 0;white-space:nowrap;letter-spacing:.02em}
    #atropbot-console .atrop-chead{display:flex;align-items:center;gap:8px;padding:9px 12px;background:rgba(15,23,42,.95);
      border-bottom:1px solid rgba(56,189,248,.25);font-weight:700;letter-spacing:.12em;font-size:10px;text-transform:uppercase;color:#7dd3fc}
    #atropbot-console .atrop-cdot{width:8px;height:8px;border-radius:50%;background:#38bdf8;box-shadow:0 0 8px #38bdf8;animation:atrop-blink 1s infinite}
    #atropbot-console .atrop-ccount{margin-left:auto;color:#64748b;font-weight:600;letter-spacing:normal}
    #atropbot-console .atrop-cbody{overflow-y:auto;padding:8px 10px;scrollbar-width:thin;scrollbar-color:#334155 transparent}
    #atropbot-console .atrop-cbody::-webkit-scrollbar{width:8px}
    #atropbot-console .atrop-cbody::-webkit-scrollbar-thumb{background:#334155;border-radius:4px}
    #atropbot-console .atrop-row{padding:2px 0;border-bottom:1px solid rgba(148,163,184,.08);white-space:pre-wrap;word-break:break-word;display:flex;gap:7px}
    #atropbot-console .atrop-ts{color:#475569;flex:0 0 auto}
    #atropbot-console .atrop-msg{flex:1 1 auto}
    .atrop-lv-info .atrop-msg{color:#e2e8f0}
    .atrop-lv-ok .atrop-msg{color:#4ade80}
    .atrop-lv-warn .atrop-msg{color:#fbbf24}
    .atrop-lv-erro .atrop-msg{color:#f87171;font-weight:700}
    .atrop-lv-calc .atrop-msg{color:#7dd3fc}
  `;
  (document.head || document.documentElement).appendChild(st);

  const layer = document.createElement('div'); layer.id = 'atropbot-layer';
  const svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('style', 'position:absolute;inset:0;width:100%;height:100%');
  layer.appendChild(svg);
  const cursor = document.createElement('div'); cursor.id = 'atropbot-cursor';
  const thought = document.createElement('div'); thought.id = 'atropbot-thought'; thought.style.display = 'none';
  layer.appendChild(cursor); layer.appendChild(thought);
  (document.body || document.documentElement).appendChild(layer);

  let px = window.innerWidth / 2, py = window.innerHeight - 90;
  cursor.style.left = px + 'px'; cursor.style.top = py + 'px';

  // Console ao vivo (bastidores) — feed rolável do que está acontecendo.
  const con = document.createElement('div'); con.id = 'atropbot-console';
  con.innerHTML = '<div class="atrop-chead"><span class="atrop-cdot"></span>ATROPBOT · CONSOLE'
    + '<span class="atrop-ccount" id="atropbot-ccount">0</span></div>'
    + '<div class="atrop-cbody" id="atropbot-cbody"></div>';
  document.body.appendChild(con);

  const A = {
    _pos: { x: px, y: py },
    _n: 0,
    log: function (nivel, msg) {
      const body = document.getElementById('atropbot-cbody');
      if (!body) return;
      const now = new Date();
      const hh = String(now.getHours()).padStart(2, '0');
      const mm = String(now.getMinutes()).padStart(2, '0');
      const ss = String(now.getSeconds()).padStart(2, '0');
      const row = document.createElement('div');
      row.className = 'atrop-row atrop-lv-' + (nivel || 'info');
      row.innerHTML = '<span class="atrop-ts">' + hh + ':' + mm + ':' + ss + '</span>'
        + '<span class="atrop-msg">' + String(msg).replace(/</g, '&lt;') + '</span>';
      body.appendChild(row);
      while (body.childNodes.length > 250) body.removeChild(body.firstChild);
      const perto = body.scrollHeight - body.scrollTop - body.clientHeight < 60;
      if (perto) body.scrollTop = body.scrollHeight;
      this._n++;
      const c = document.getElementById('atropbot-ccount');
      if (c) c.textContent = this._n;
    },
    status: function (msg, cor) {
      let h = document.getElementById('atropbot-hud');
      if (!h) { h = document.createElement('div'); h.id = 'atropbot-hud'; document.body.appendChild(h); }
      cor = cor || '#22c55e';
      h.style.borderLeftColor = cor;
      h.innerHTML = '<div class="atrop-tag"><span class="atrop-dot" style="background:' + cor +
        ';box-shadow:0 0 8px ' + cor + '"></span>ATROPBOT</div>' + String(msg).replace(/</g, '&lt;');
    },
    moveTo: function (x, y, label, cor) {
      cor = cor || '#38bdf8';
      const line = document.createElementNS(NS, 'line');
      line.setAttribute('x1', this._pos.x); line.setAttribute('y1', this._pos.y);
      line.setAttribute('x2', x); line.setAttribute('y2', y);
      line.setAttribute('stroke', cor); line.setAttribute('stroke-width', '2.5');
      line.setAttribute('stroke-linecap', 'round'); line.setAttribute('stroke-dasharray', '9 7');
      line.style.filter = 'drop-shadow(0 0 5px ' + cor + ')';
      svg.appendChild(line);
      line.animate([{ opacity: .95 }, { opacity: 0 }], { duration: 1300, easing: 'ease-out' })
        .onfinish = () => line.remove();
      cursor.style.left = x + 'px'; cursor.style.top = y + 'px';
      cursor.style.borderColor = cor;
      if (label) { thought.style.display = 'block'; thought.textContent = label; thought.style.borderColor = cor; }
      thought.style.left = x + 'px'; thought.style.top = y + 'px';
      this._pos = { x: x, y: y };
      setTimeout(() => {
        const r = document.createElement('div'); r.className = 'atrop-ring';
        r.style.left = x + 'px'; r.style.top = y + 'px'; r.style.borderColor = cor;
        layer.appendChild(r); setTimeout(() => r.remove(), 1000);
      }, 560);
    },
    ripple: function (x, y) {
      const r = document.createElement('div'); r.className = 'atrop-ripple';
      r.style.left = x + 'px'; r.style.top = y + 'px';
      layer.appendChild(r); setTimeout(() => r.remove(), 600);
    },
    box: function (x, y, w, h, label, cor) {
      cor = cor || '#22c55e';
      const b = document.createElement('div'); b.className = 'atrop-box';
      b.style.left = x + 'px'; b.style.top = y + 'px';
      b.style.width = Math.max(w, 6) + 'px'; b.style.height = Math.max(h, 6) + 'px';
      b.style.borderColor = cor; b.style.boxShadow = '0 0 0 2px ' + cor + '40,0 0 12px ' + cor + '80';
      if (label) {
        const t = document.createElement('span'); t.textContent = label;
        t.style.background = cor; b.appendChild(t);
      }
      layer.appendChild(b);
      setTimeout(() => { b.style.opacity = '0'; setTimeout(() => b.remove(), 300); }, 1700);
    }
  };
  window.__ATROPBOT = A;
})();
"""


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

    def _log(self, mensagem, nivel=None):
        db.registrar_log_geral(mensagem)
        self._log_bus.publicar({"tipo": "log_geral", "mensagem": mensagem, "hora": time.time()})
        # Espelha o log no HUD + console "estilo Tesla" na própria tela (best-effort).
        if self._page_atual is not None:
            self._hud(self._page_atual, mensagem)
            self._console(self._page_atual, mensagem, nivel or self._nivel_auto(mensagem))
        item_id = self._maquina.item_atual_id
        if item_id is not None:
            db.registrar_log_item(item_id, mensagem)
            self._log_bus.publicar({"tipo": "log_item", "item_id": item_id, "mensagem": mensagem, "hora": time.time()})

    def _debug(self, mensagem):
        """Linha 'bastidores' (cálculos/decisões): vai pro console azul-claro
        na tela e também é persistida no log normal, pra ajudar a caçar bug."""
        self._log("· " + mensagem, nivel="calc")

    @staticmethod
    def _nivel_auto(mensagem):
        """Classifica a cor da linha no console a partir do texto."""
        m = (mensagem or "").lower()
        if any(t in m for t in ("erro", "não consegui", "nao consegui", "falha", "sem ctr", "inválid", "invalid", "exception")):
            return "erro"
        if any(t in m for t in ("alerta", "aviso", "vencid", "pausad", "pulando", "pulad", "retent", "reenfile")):
            return "warn"
        if any(t in m for t in ("sucesso", "agendado", "concluíd", "concluid", "escolhida", "confirmado", "ok")):
            return "ok"
        return "info"

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
                cor_evento = "#ef4444" if tipo == "erro" else ("#22c55e" if tipo == "sucesso" else "#38bdf8")
                self._contornar(page, elemento, f"Trizy diz: {texto[:40]}", cor=cor_evento)
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

    def _datepicker_cnh(self, page):
        """Localiza o md-datepicker da 'Validade da CNH' (o campo 'Insira uma
        data' no bloco da CNH)."""
        tentativas = [
            "md-datepicker:has(input[placeholder*='Insira uma data' i])",
            "xpath=(//*[contains(normalize-space(.),'CNH')]/following::md-datepicker)[1]",
        ]
        for sel in tentativas:
            try:
                loc = page.locator(sel)
                if loc.count() > 0:
                    return loc.first
            except Exception:
                continue
        return page.locator("md-datepicker").first

    def _datepicker_contrato(self, page):
        """Localiza o md-datepicker da seção 'Contrato' (a Data da Cota) — o
        que fica logo abaixo do título 'Contrato' e antes do campo 'Cota'.
        Antes usávamos `.last`, que às vezes pegava outro datepicker da tela."""
        tentativas = [
            "xpath=(//*[normalize-space(text())='Contrato']/following::md-datepicker)[1]",
            "xpath=(//md-datepicker[following::*[contains(normalize-space(.),'Fração de cota')]])[last()]",
            "xpath=(//md-datepicker[following::*[contains(normalize-space(.),'Cota')]])[last()]",
        ]
        for sel in tentativas:
            try:
                loc = page.locator(sel)
                if loc.count() > 0:
                    return loc.first
            except Exception:
                continue
        return page.locator("md-datepicker").last

    def _calendario_aberto(self, page):
        try:
            return page.locator(
                "md-calendar, .md-datepicker-calendar-pane, tbody.md-calendar-month, td.md-calendar-date"
            ).first.is_visible(timeout=800)
        except Exception:
            return False

    def _abrir_datepicker(self, page, placa, rotulo, datepicker):
        """Abre o calendário de um md-datepicker tentando vários gatilhos
        (o ícone de calendário, o container do input, o próprio input...),
        porque dependendo do campo o clique cai em elementos diferentes."""
        candidatos = [
            datepicker.locator("button.md-datepicker-button"),
            datepicker.locator(".md-datepicker-button"),
            datepicker.locator("md-icon"),
            datepicker.locator(".md-datepicker-input-container"),
            datepicker.locator("button"),
            datepicker.locator("input"),
        ]
        for cand in candidatos:
            try:
                el = cand.first
                if el.count() == 0 or not el.is_visible():
                    continue
                self._apontar(page, el, f"{rotulo}: abrir calendário", cor="#3b82f6")
                el.click(force=True)
                time.sleep(0.7)
                if self._calendario_aberto(page):
                    return True
            except Exception:
                continue
        return self._calendario_aberto(page)

    def _selecionar_data_calendario(self, page, placa, rotulo, alvo, datepicker):
        """ESCOLHE uma data clicando no calendário do Trizy (md-datepicker):
        abre o calendário -> navega mês a mês até o mês/ano alvo -> clica no
        dia. É assim que o Trizy registra a data de verdade (apenas digitar
        não dispara o evento Angular que habilita a Cota)."""
        alvo_mes_ano = f"{MESES_PT[alvo.month - 1]} {alvo.year}"
        alvo_str = alvo.strftime("%d/%m/%Y")
        sel_mes = f"tbody.md-calendar-month:has(td.md-calendar-month-label:text-is('{alvo_mes_ano}'))"
        try:
            self._hud(page, f"{rotulo}: abrindo o calendário…", cor="#3b82f6")
            if not self._abrir_datepicker(page, placa, rotulo, datepicker):
                self._log(f"[{placa}] Não consegui ABRIR o calendário da {rotulo} — o clique no ícone não abriu o popup.")
                return False

            # Navega até o mês/ano alvo usando as setas do calendário.
            hoje = datetime.now().date()
            para_frente = alvo >= hoje
            direcao = "avançar" if para_frente else "voltar"
            self._debug(f"{rotulo}: calendário aberto. Alvo={alvo_str} → navegar mês a mês ({direcao}) até {alvo_mes_ano}.")
            seta_prox = page.locator(
                "button.md-calendar-next-month, button[aria-label*='Próximo' i], button[aria-label*='Next' i]"
            ).first
            seta_ant = page.locator(
                "button.md-calendar-previous-month, button[aria-label*='Anterior' i], button[aria-label*='Previous' i]"
            ).first
            seta = seta_prox if para_frente else seta_ant

            def _mes_visivel():
                try:
                    return page.locator(sel_mes).first.is_visible(timeout=400)
                except Exception:
                    return False

            passos = 0
            for _ in range(60):
                if _mes_visivel():
                    break
                if seta.count() > 0 and seta.is_visible():
                    seta.click(force=True)
                    passos += 1
                    time.sleep(0.12)
                else:
                    break
            self._debug(f"{rotulo}: {passos} clique(s) de mês até chegar em {alvo_mes_ano}.")

            # Clica no dia DENTRO do mês alvo (evita pegar o mesmo número de
            # um mês vizinho num calendário rolável).
            mes_tbody = page.locator(sel_mes).first
            escopo = mes_tbody if mes_tbody.count() > 0 else page
            dia = escopo.locator(
                "td.md-calendar-date:not(.md-calendar-date-disabled) "
                f".md-calendar-date-selection-indicator:text-is('{alvo.day}')"
            ).first
            self._apontar(page, dia, f"{rotulo}: dia {alvo.day}", cor="#22c55e")
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
        hoje = datetime.now().date()
        alvo = hoje + timedelta(days=CNH_DIAS_BUFFER)
        self._debug(
            f"Cálculo CNH: hoje {hoje.strftime('%d/%m/%Y')} + {CNH_DIAS_BUFFER} dias "
            f"= {alvo.strftime('%d/%m/%Y')} (só aplica se estiver vazia/vencida)."
        )
        try:
            datepicker = self._datepicker_cnh(page)
            valor_atual = ""
            try:
                valor_atual = (datepicker.locator("input").first.input_value(timeout=1000) or "").strip()
            except Exception:
                valor_atual = ""
            self._ver(page, datepicker.locator("input").first, "Validade CNH (atual)")
            if not self._data_vencida_ou_vazia(valor_atual):
                self._log(f"[{placa}] Validade da CNH já é futura ({valor_atual}). Mantendo.")
                return
            self._log(
                f"[{placa}] Validade da CNH vazia/vencida ({valor_atual or 'vazia'}). "
                f"Ajustando para {alvo.strftime('%d/%m/%Y')} pelo calendário."
            )
            self._selecionar_data_calendario(page, placa, "Validade da CNH", alvo, datepicker)
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
        self._debug(f"Cálculo Data da Cota: '{data_cota}' → dia {alvo.day} de {MESES_PT[alvo.month - 1]} {alvo.year}.")
        datepicker = self._datepicker_contrato(page)
        self._selecionar_data_calendario(page, placa, "Data da Cota", alvo, datepicker)

    def _garantir_tesla(self, page):
        """Garante que o motor do overlay 'Tesla' está injetado na página."""
        try:
            if not page.evaluate("() => !!window.__ATROPBOT"):
                page.evaluate(TESLA_ENGINE_JS)
        except Exception:
            pass

    def _hud(self, page, texto, cor="#22c55e"):
        """Atualiza o painel de status do overlay 'Tesla' na tela do Trizy.
        Best-effort — a página pode estar navegando/sem contexto."""
        try:
            self._garantir_tesla(page)
            page.evaluate(
                "([m, c]) => { if (window.__ATROPBOT) window.__ATROPBOT.status(m, c); }",
                [texto, cor],
            )
        except Exception:
            pass

    def _console(self, page, texto, nivel="info"):
        """Adiciona uma linha no CONSOLE ao vivo (bastidores) da tela do Trizy.
        Best-effort."""
        try:
            self._garantir_tesla(page)
            page.evaluate(
                "([n, m]) => { if (window.__ATROPBOT) window.__ATROPBOT.log(n, m); }",
                [nivel, texto],
            )
        except Exception:
            pass

    def _contornar(self, page, locator, rotulo="", cor="#22c55e"):
        """Desenha uma CAIXA (retângulo colorido com rótulo) em volta do
        elemento no overlay, mostrando o que o robô está enxergando. Não lê
        conteúdo nem escreve no console. Best-effort."""
        self._garantir_tesla(page)
        try:
            box = locator.bounding_box()
        except Exception:
            box = None
        if not box:
            return
        rotulo_curto = rotulo if len(rotulo) <= 48 else rotulo[:47] + "…"
        try:
            page.evaluate(
                "([x, y, w, h, l, c]) => { if (window.__ATROPBOT) window.__ATROPBOT.box(x, y, w, h, l, c); }",
                [box["x"], box["y"], box["width"], box["height"], rotulo_curto, cor],
            )
        except Exception:
            pass

    def _ver(self, page, locator, rotulo, ler=True):
        """"Modo percepção": contorna o elemento com uma CAIXA VERDE (como um
        detector), lê o conteúdo dele (valor do input ou texto) e escreve no
        console o que foi lido — deixando exposto o que o robô vê/lê. Só
        visual (best-effort). Retorna o texto lido (ou "")."""
        conteudo = ""
        try:
            locator.scroll_into_view_if_needed(timeout=1500)
        except Exception:
            pass
        if ler:
            try:
                conteudo = (locator.input_value(timeout=600) or "").strip()
            except Exception:
                conteudo = ""
            if not conteudo:
                try:
                    conteudo = (locator.inner_text(timeout=600) or "").strip()
                except Exception:
                    conteudo = ""
        conteudo = " ".join(conteudo.split())
        self._contornar(page, locator, rotulo, cor="#22c55e")
        lido = conteudo if conteudo else "(vazio)"
        self._console(page, f"👁 {rotulo}: {lido[:120]}", nivel="ok")
        return conteudo

    def _apontar(self, page, locator, label="", cor="#38bdf8"):
        """"Mira" no elemento: leva o cursor do overlay até ele (com rastro),
        mostra o balão de ação e pulsa um anel onde vai clicar — depois
        contorna o elemento. É só visual (best-effort)."""
        try:
            locator.scroll_into_view_if_needed(timeout=1500)
        except Exception:
            pass
        self._garantir_tesla(page)
        try:
            box = locator.bounding_box()
        except Exception:
            box = None
        if box:
            cx = box["x"] + box["width"] / 2
            cy = box["y"] + box["height"] / 2
            try:
                page.evaluate(
                    "([x, y, l, c]) => { if (window.__ATROPBOT) window.__ATROPBOT.moveTo(x, y, l, c); }",
                    [cx, cy, label, cor],
                )
                time.sleep(0.7)  # deixa o cursor "andar" até o alvo antes do clique
                page.evaluate(
                    "([x, y]) => { if (window.__ATROPBOT) window.__ATROPBOT.ripple(x, y); }",
                    [cx, cy],
                )
            except Exception:
                pass
        self._destacar(page, locator)

    def _destacar(self, page, locator):
        """Desenha um contorno temporário no elemento que o robô vai usar."""
        try:
            locator.evaluate(
                """(el) => {
                    const anterior = el.style.outline;
                    el.style.outline = '3px solid #38bdf8';
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

                tent = tentativas.get(item_id, 1)
                self._debug(
                    f"Item {_idx}/{len(fila_trabalho)} (tentativa {tent}/{MAX_TENTATIVAS_ITEM}) | "
                    f"placa={placa} cpf={cpf} | terminal={fs_destino} fazenda={fazenda} "
                    f"contrato={contrato} data_cota={data_cota or '—'}"
                )

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

                    btn_agendar = page.get_by_role("button", name="AGENDAR").first
                    self._apontar(page, btn_agendar, "Abrir Novo Agendamento", cor="#3b82f6")
                    btn_agendar.click()
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
                    self._ver(page, page.locator("input[aria-label*='CPF']").first, "CPF")
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
                    self._ver(page, page.locator("md-select[aria-label*='Composição']").first, "Composição")
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
                        self._ver(page, campo_placa, "Placa da Tração")
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
                        self._apontar(page, popup_cota, "Selecionar Cota/CTR", cor="#22c55e")
                        popup_cota.click()
                    except Exception:
                        raise Exception(f"Sem CTR ({contrato}) no painel.")

                    time.sleep(1)
                    self._ver(page, page.locator("md-input-container:has(label:has-text('Cota')) input").first, "Cota/CTR")
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
                    self._apontar(page, botao_agendar_final, "Clicar em AGENDAR", cor="#22c55e")
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