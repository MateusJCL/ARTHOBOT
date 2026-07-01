# ==========================================
# CORE/ESTADO.PY - Máquina de estados central do ATROPBOT.
#
# No app antigo (AUTOMATROM/Tkinter), cada situação de pausa tinha seu
# próprio threading.Event e suas próprias flags soltas no RoboAutomatrom
# (pausado, fila_pausada_por_ctr, fila_pausada_por_navegador_fechado...),
# sincronizadas à mão com janela.after(). Isso é frágil por construção:
# é fácil dois pedaços de código discordarem sobre "o que está
# acontecendo agora", e foi a causa raiz dos bugs de tela em branco e
# travamento.
#
# Aqui, existe UM objeto (Maquina) com UM estado por vez, protegido por
# UM lock. Qualquer parte do sistema (robô, servidor web) só lê/escreve
# através dele. Não existe estado duplicado em variáveis soltas.
# ==========================================
import threading
from enum import Enum


class Status(Enum):
    PARADO = "parado"
    RODANDO = "rodando"
    PAUSADO_MANUAL = "pausado_manual"
    PAUSADO_CTR = "pausado_ctr"
    PAUSADO_NAVEGADOR = "pausado_navegador"
    PAUSADO_ERRO_TRIZY = "pausado_erro_trizy"
    AGUARDANDO_LOGIN = "aguardando_login"
    AGUARDANDO_GUIADO = "aguardando_guiado"


class Maquina:
    """Única fonte de verdade sobre o que o robô está fazendo agora.
    Thread-safe: todo acesso passa pelo lock interno."""

    def __init__(self):
        self._lock = threading.RLock()
        self._status = Status.PARADO
        self._contexto = {}
        self._evt_liberar = threading.Event()
        self._evt_liberar.set()
        self._evt_checkpoint = threading.Event()
        self.cancelado = False
        self.modo_guiado = False
        self.item_atual_id = None

    def status(self):
        with self._lock:
            return self._status

    def contexto(self):
        with self._lock:
            return dict(self._contexto)

    def snapshot(self):
        with self._lock:
            return {
                "status": self._status.value,
                "contexto": dict(self._contexto),
                "item_atual_id": self.item_atual_id,
                "modo_guiado": self.modo_guiado,
            }

    def iniciar_execucao(self):
        with self._lock:
            self._status = Status.RODANDO
            self._contexto = {}
            self.cancelado = False
            self._evt_liberar.set()

    def pausar_manual(self):
        with self._lock:
            if self._status != Status.RODANDO:
                return False
            self._status = Status.PAUSADO_MANUAL
            self._evt_liberar.clear()
            return True

    def retomar_manual(self):
        with self._lock:
            if self._status != Status.PAUSADO_MANUAL:
                return False
            self._status = Status.RODANDO
            self._evt_liberar.set()
            return True

    def pausar_por_ctr(self, item_id, terminal, fazenda, contrato):
        with self._lock:
            self._status = Status.PAUSADO_CTR
            self._contexto = {
                "item_id": item_id, "terminal": terminal,
                "fazenda": fazenda, "contrato": contrato,
            }
            self._evt_liberar.clear()

    def resolver_ctr(self, pular_lote):
        with self._lock:
            if self._status != Status.PAUSADO_CTR:
                return None
            ctx = dict(self._contexto)
            self._status = Status.RODANDO
            self._contexto = {"pular_lote": pular_lote, **ctx}
            self._evt_liberar.set()
            return ctx

    def pausar_por_erro_trizy(self, item_id, mensagem):
        """O próprio Trizy mostra um banner de erro na tela (ex.: aviso
        de instabilidade/conexão) — diferente de um erro que o robô
        detecta por timeout de seletor, este é um aviso ATIVO do site.
        Pausa a fila inteira (não só o item) e pede decisão do usuário,
        igual à trava de CTR inválido."""
        with self._lock:
            self._status = Status.PAUSADO_ERRO_TRIZY
            self._contexto = {"item_id": item_id, "mensagem": mensagem}
            self._evt_liberar.clear()

    def resolver_erro_trizy(self, cancelar=False):
        with self._lock:
            if self._status != Status.PAUSADO_ERRO_TRIZY:
                return False
            if cancelar:
                self.cancelado = True
                self._status = Status.PARADO
            else:
                self._status = Status.RODANDO
            self._contexto = {}
            self._evt_liberar.set()
            return True

    def pausar_por_navegador_fechado(self, item_id=None):
        """Chamado tanto pelo monitor instantâneo (context.on('close'))
        quanto por uma exceção do Playwright pega no meio de uma ação —
        os dois caminhos convergem para o MESMO estado central, então a
        UI nunca vê dois sinais conflitantes."""
        with self._lock:
            if self._status == Status.PAUSADO_NAVEGADOR:
                return False
            self._status = Status.PAUSADO_NAVEGADOR
            self._contexto = {"item_id": item_id}
            self._evt_liberar.clear()
            return True

    def resolver_navegador_fechado(self, cancelar=False):
        with self._lock:
            if self._status != Status.PAUSADO_NAVEGADOR:
                return False
            if cancelar:
                self.cancelado = True
                self._status = Status.PARADO
            else:
                self._status = Status.RODANDO
            self._contexto = {}
            self._evt_liberar.set()
            return True

    def entrar_aguardando_login(self):
        with self._lock:
            self._status = Status.AGUARDANDO_LOGIN

    def sair_aguardando_login(self):
        with self._lock:
            if self._status == Status.AGUARDANDO_LOGIN:
                self._status = Status.RODANDO

    def entrar_checkpoint_guiado(self, item_id, nome_etapa):
        with self._lock:
            self._status = Status.AGUARDANDO_GUIADO
            self._contexto = {"item_id": item_id, "nome_etapa": nome_etapa}
            self._evt_checkpoint.clear()

    def continuar_checkpoint_guiado(self):
        with self._lock:
            self._evt_checkpoint.set()
            if self._status == Status.AGUARDANDO_GUIADO:
                self._status = Status.RODANDO
                self._contexto = {}

    def aguardar_checkpoint_guiado(self):
        self._evt_checkpoint.wait()

    def cancelar(self):
        with self._lock:
            self.cancelado = True
            self._status = Status.PARADO
            self._contexto = {}
            self._evt_liberar.set()
            self._evt_checkpoint.set()

    def finalizar(self):
        with self._lock:
            self._status = Status.PARADO
            self._contexto = {}
            self.item_atual_id = None
            self._evt_liberar.set()

    def esperar_liberar(self):
        """Bloqueia a thread do robô enquanto o estado atual exigir
        pausa. Usado no lugar dos múltiplos `_evt_pausa.wait()`
        espalhados pelo robô antigo."""
        self._evt_liberar.wait()

    def esta_pausado(self):
        with self._lock:
            return self._status in (
                Status.PAUSADO_MANUAL, Status.PAUSADO_CTR, Status.PAUSADO_NAVEGADOR,
                Status.PAUSADO_ERRO_TRIZY,
            )


class LogBus:
    """Barramento simples para notificar a interface (via Server-Sent
    Events) sem polling agressivo. O histórico fica no banco (core.db);
    um cliente que reconectar busca pelo último id visto."""

    def __init__(self):
        self._assinantes = []
        self._lock = threading.Lock()

    def assinar(self):
        fila = []
        with self._lock:
            self._assinantes.append(fila)
        return fila

    def cancelar_assinatura(self, fila):
        with self._lock:
            if fila in self._assinantes:
                self._assinantes.remove(fila)

    def publicar(self, evento):
        with self._lock:
            for fila in self._assinantes:
                fila.append(evento)
