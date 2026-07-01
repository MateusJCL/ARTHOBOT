# ==========================================
# CORE/DB.PY - Acesso ao SQLite, isolado do resto do app.
# ==========================================
import sqlite3
import threading
import time
import os

DB_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "atropbot.db")

_lock = threading.Lock()


def _conn():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def setup_db():
    with _lock:
        conn = _conn()
        c = conn.cursor()
        c.execute("""CREATE TABLE IF NOT EXISTS veiculos
                     (placa TEXT PRIMARY KEY, motorista TEXT, cpf TEXT)""")
        c.execute("""CREATE TABLE IF NOT EXISTS fazendas (nome TEXT PRIMARY KEY)""")
        c.execute("""CREATE TABLE IF NOT EXISTS contratos (numero TEXT PRIMARY KEY)""")
        c.execute("""CREATE TABLE IF NOT EXISTS fazenda_contrato
                     (fazenda TEXT, contrato TEXT, PRIMARY KEY (fazenda, contrato))""")
        c.execute("""CREATE TABLE IF NOT EXISTS credenciais_trizy
                     (id INTEGER PRIMARY KEY, email TEXT, senha TEXT)""")
        c.execute("SELECT count(*) FROM credenciais_trizy")
        if c.fetchone()[0] == 0:
            c.execute("INSERT INTO credenciais_trizy (id, email, senha) VALUES (1, '', '')")

        c.execute("""CREATE TABLE IF NOT EXISTS fila_itens (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        terminal TEXT,
                        fazenda TEXT,
                        contrato TEXT,
                        placa TEXT,
                        cpf TEXT,
                        status TEXT,
                        criado_em REAL,
                        ordem INTEGER
                     )""")
        # Migração segura para bancos já existentes (criados antes da
        # coluna 'ordem' existir) — adiciona a coluna se ainda não tiver.
        c.execute("PRAGMA table_info(fila_itens)")
        colunas_existentes = {linha[1] for linha in c.fetchall()}
        if "ordem" not in colunas_existentes:
            c.execute("ALTER TABLE fila_itens ADD COLUMN ordem INTEGER")
        c.execute("""CREATE TABLE IF NOT EXISTS fila_log (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        item_id INTEGER,
                        hora REAL,
                        mensagem TEXT
                     )""")
        c.execute("""CREATE TABLE IF NOT EXISTS log_geral (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        hora REAL,
                        mensagem TEXT
                     )""")
        # NOVO: captura genérica de tudo que aparece NA TELA DO TRIZY
        # (não erros do robô — avisos/banners/popups que o PRÓPRIO site
        # exibe). É a base de dados real para depois refinar a detecção
        # automática de erros específicos, em vez de ficar chutando
        # seletores sem ver o que de fato acontece em produção.
        c.execute("""CREATE TABLE IF NOT EXISTS eventos_trizy (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        hora REAL,
                        tipo TEXT,
                        item_id INTEGER,
                        placa TEXT,
                        texto TEXT,
                        screenshot_path TEXT
                     )""")
        conn.commit()
        conn.close()


# ---------------- VEÍCULOS ----------------
def listar_veiculos():
    with _lock:
        conn = _conn()
        c = conn.cursor()
        c.execute("SELECT placa, motorista, cpf FROM veiculos ORDER BY placa")
        rows = c.fetchall()
        conn.close()
        return rows


def salvar_veiculo(placa, motorista, cpf):
    with _lock:
        conn = _conn()
        c = conn.cursor()
        c.execute(
            "INSERT OR REPLACE INTO veiculos (placa, motorista, cpf) VALUES (?, ?, ?)",
            (placa, motorista, cpf),
        )
        conn.commit()
        conn.close()


def editar_veiculo(placa_original, nova_placa, motorista, cpf):
    with _lock:
        conn = _conn()
        c = conn.cursor()
        if placa_original != nova_placa:
            c.execute("DELETE FROM veiculos WHERE placa=?", (placa_original,))
        c.execute(
            "INSERT OR REPLACE INTO veiculos (placa, motorista, cpf) VALUES (?, ?, ?)",
            (nova_placa, motorista, cpf),
        )
        conn.commit()
        conn.close()


def excluir_veiculos(placas):
    with _lock:
        conn = _conn()
        c = conn.cursor()
        c.executemany("DELETE FROM veiculos WHERE placa=?", [(p,) for p in placas])
        conn.commit()
        conn.close()


def buscar_cpf_por_placa(placa):
    with _lock:
        conn = _conn()
        c = conn.cursor()
        c.execute("SELECT cpf FROM veiculos WHERE placa=?", (placa,))
        res = c.fetchone()
        conn.close()
        return res[0] if res else None


def importar_veiculos_csv(linhas):
    with _lock:
        conn = _conn()
        c = conn.cursor()
        contador = 0
        for placa, motorista, cpf in linhas:
            if placa and cpf:
                c.execute(
                    "INSERT OR REPLACE INTO veiculos (placa, motorista, cpf) VALUES (?, ?, ?)",
                    (placa.upper(), motorista.upper(), cpf),
                )
                contador += 1
        conn.commit()
        conn.close()
        return contador


# ---------------- SUGESTÕES (autocomplete) ----------------
def sugestoes(tabela, coluna, texto):
    permitido = {
        ("veiculos", "placa"),
        ("fazendas", "nome"),
        ("contratos", "numero"),
    }
    if (tabela, coluna) not in permitido:
        raise ValueError("Tabela/coluna não permitida para autocomplete.")
    with _lock:
        conn = _conn()
        c = conn.cursor()
        if texto:
            c.execute(f"SELECT {coluna} FROM {tabela} WHERE {coluna} LIKE ? ORDER BY {coluna} LIMIT 30", (f"%{texto}%",))
        else:
            c.execute(f"SELECT {coluna} FROM {tabela} ORDER BY {coluna} LIMIT 200")
        resultados = [row[0] for row in c.fetchall()]
        conn.close()
        return resultados


def listar_fazendas():
    with _lock:
        conn = _conn()
        c = conn.cursor()
        c.execute("SELECT nome FROM fazendas ORDER BY nome")
        resultados = [row[0] for row in c.fetchall()]
        conn.close()
        return resultados


def fazenda_existe(nome):
    with _lock:
        conn = _conn()
        c = conn.cursor()
        c.execute("SELECT 1 FROM fazendas WHERE nome=?", (nome,))
        res = c.fetchone()
        conn.close()
        return res is not None


def registrar_contrato(contrato):
    with _lock:
        conn = _conn()
        c = conn.cursor()
        if contrato:
            c.execute("INSERT OR IGNORE INTO contratos (numero) VALUES (?)", (contrato,))
        conn.commit()
        conn.close()


# ---------------- VÍNCULO FAZENDA -> CONTRATO (UNIFICADO) ----------------
def listar_vinculos_fazenda_contrato():
    with _lock:
        conn = _conn()
        c = conn.cursor()
        c.execute("SELECT fazenda, contrato FROM fazenda_contrato ORDER BY fazenda, contrato")
        rows = c.fetchall()
        conn.close()
        return rows


def salvar_vinculo_fazenda_contrato(fazenda, contrato):
    with _lock:
        conn = _conn()
        c = conn.cursor()
        c.execute("INSERT OR IGNORE INTO fazendas (nome) VALUES (?)", (fazenda,))
        c.execute("INSERT OR IGNORE INTO contratos (numero) VALUES (?)", (contrato,))
        c.execute(
            "INSERT OR IGNORE INTO fazenda_contrato (fazenda, contrato) VALUES (?, ?)",
            (fazenda, contrato),
        )
        conn.commit()
        conn.close()


def excluir_vinculos_fazenda_contrato(pares):
    with _lock:
        conn = _conn()
        c = conn.cursor()
        c.executemany("DELETE FROM fazenda_contrato WHERE fazenda=? AND contrato=?", pares)
        # Limpeza opcional da tabela de fazendas caso fique órfã pode ser feita aqui no futuro
        conn.commit()
        conn.close()


def contratos_da_fazenda(fazenda):
    with _lock:
        conn = _conn()
        c = conn.cursor()
        c.execute("SELECT contrato FROM fazenda_contrato WHERE fazenda=? ORDER BY contrato", (fazenda,))
        resultados = [row[0] for row in c.fetchall()]
        conn.close()
        return resultados


# ---------------- CREDENCIAIS TRIZY ----------------
def obter_credenciais_trizy():
    with _lock:
        conn = _conn()
        c = conn.cursor()
        c.execute("SELECT email, senha FROM credenciais_trizy WHERE id=1")
        row = c.fetchone()
        conn.close()
        return row if row else ("", "")


def salvar_credenciais_trizy(email, senha):
    with _lock:
        conn = _conn()
        c = conn.cursor()
        c.execute("UPDATE credenciais_trizy SET email=?, senha=? WHERE id=1", (email, senha))
        conn.commit()
        conn.close()


# ---------------- FILA (persistida) ----------------
def listar_fila():
    with _lock:
        conn = _conn()
        c = conn.cursor()
        c.execute("""SELECT id, terminal, fazenda, contrato, placa, cpf, status
                     FROM fila_itens ORDER BY COALESCE(ordem, id), id""")
        rows = c.fetchall()
        conn.close()
        return rows


def reorganizar_fila_por_lote():
    """Agrupa a fila por (Terminal, Fazenda, Contrato): todos os itens
    de um mesmo lote ficam juntos, minimizando quantas vezes o robô
    precisa trocar de Terminal/CTR durante a execução. Dentro de cada
    lote, a ordem de chegada original é preservada. A ordem dos PRÓPRIOS
    lotes segue a ordem em que cada lote apareceu pela primeira vez na
    fila (não reordena alfabeticamente — respeita a intenção de quem
    montou a fila: o que foi adicionado primeiro continua sendo
    processado primeiro, só os veículos do mesmo lote é que se juntam).
    Itens já com status 'Sucesso' não são tocados na MAQUINA física de
    ordem, mas como o agrupamento é estável, eles naturalmente
    permanecem no lugar do seu lote.
    """
    with _lock:
        conn = _conn()
        c = conn.cursor()
        c.execute("""SELECT id, terminal, fazenda, contrato
                     FROM fila_itens ORDER BY COALESCE(ordem, id), id""")
        linhas = c.fetchall()

        primeira_aparicao = {}
        for item_id, terminal, fazenda, contrato in linhas:
            chave = (terminal, fazenda, contrato)
            if chave not in primeira_aparicao:
                primeira_aparicao[chave] = len(primeira_aparicao)

        linhas_ordenadas = sorted(
            linhas,
            key=lambda linha: (primeira_aparicao[(linha[1], linha[2], linha[3])], linha[0]),
        )

        for nova_ordem, (item_id, *_resto) in enumerate(linhas_ordenadas):
            c.execute("UPDATE fila_itens SET ordem=? WHERE id=?", (nova_ordem, item_id))

        conn.commit()
        conn.close()


def listar_fila_com_indice_lote():
    """Como listar_fila(), mas cada item também traz um 'indice_lote'
    (0, 1, 2...) — usado pela interface para colorir/alternar visualmente
    cada grupo de Terminal+Fazenda+Contrato na tabela da fila."""
    rows = listar_fila()
    indice_por_chave = {}
    resultado = []
    for item_id, terminal, fazenda, contrato, placa, cpf, status in rows:
        chave = (terminal, fazenda, contrato)
        if chave not in indice_por_chave:
            indice_por_chave[chave] = len(indice_por_chave)
        resultado.append(
            (item_id, terminal, fazenda, contrato, placa, cpf, status, indice_por_chave[chave])
        )
    return resultado


def adicionar_item_fila(terminal, fazenda, contrato, placa, cpf, status="Aguardando..."):
    with _lock:
        conn = _conn()
        c = conn.cursor()
        c.execute("SELECT COALESCE(MAX(ordem), -1) FROM fila_itens")
        proxima_ordem = c.fetchone()[0] + 1
        c.execute(
            """INSERT INTO fila_itens (terminal, fazenda, contrato, placa, cpf, status, criado_em, ordem)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (terminal, fazenda, contrato, placa, cpf, status, time.time(), proxima_ordem),
        )
        conn.commit()
        novo_id = c.lastrowid
        conn.close()
        return novo_id


def atualizar_status_item(item_id, novo_status):
    with _lock:
        conn = _conn()
        c = conn.cursor()
        c.execute("UPDATE fila_itens SET status=? WHERE id=?", (novo_status, item_id))
        conn.commit()
        conn.close()


def remover_itens_fila(item_ids):
    with _lock:
        conn = _conn()
        c = conn.cursor()
        c.executemany("DELETE FROM fila_itens WHERE id=?", [(i,) for i in item_ids])
        c.executemany("DELETE FROM fila_log WHERE item_id=?", [(i,) for i in item_ids])
        conn.commit()
        conn.close()


def limpar_fila_completa():
    with _lock:
        conn = _conn()
        c = conn.cursor()
        c.execute("DELETE FROM fila_itens")
        c.execute("DELETE FROM fila_log")
        c.execute("DELETE FROM log_geral")
        conn.commit()
        conn.close()


def buscar_item_fila(item_id):
    with _lock:
        conn = _conn()
        c = conn.cursor()
        c.execute("""SELECT id, terminal, fazenda, contrato, placa, cpf, status
                     FROM fila_itens WHERE id=?""", (item_id,))
        row = c.fetchone()
        conn.close()
        return row


# ---------------- LOG (persistido) ----------------
def registrar_log_geral(mensagem):
    with _lock:
        conn = _conn()
        c = conn.cursor()
        c.execute("INSERT INTO log_geral (hora, mensagem) VALUES (?, ?)", (time.time(), mensagem))
        conn.commit()
        conn.close()


def listar_log_geral(desde_id=0, limite=500):
    with _lock:
        conn = _conn()
        c = conn.cursor()
        c.execute(
            "SELECT id, hora, mensagem FROM log_geral WHERE id > ? ORDER BY id LIMIT ?",
            (desde_id, limite),
        )
        rows = c.fetchall()
        conn.close()
        return rows


def registrar_log_item(item_id, mensagem):
    with _lock:
        conn = _conn()
        c = conn.cursor()
        c.execute(
            "INSERT INTO fila_log (item_id, hora, mensagem) VALUES (?, ?, ?)",
            (item_id, time.time(), mensagem),
        )
        conn.commit()
        conn.close()


def listar_log_item(item_id):
    with _lock:
        conn = _conn()
        c = conn.cursor()
        c.execute("SELECT hora, mensagem FROM fila_log WHERE item_id=? ORDER BY id", (item_id,))
        rows = c.fetchall()
        conn.close()
        return rows


# ---------------- EVENTOS DO TRIZY (captura genérica de tela) ----------------
def registrar_evento_trizy(tipo, texto, item_id=None, placa=None, screenshot_path=None):
    """tipo: 'sucesso' | 'erro' | 'aviso' | 'desconhecido' — registra
    qualquer coisa que apareceu na tela do Trizy, mesmo que o robô não
    saiba classificar exatamente o que é. screenshot_path é o caminho
    relativo do print tirado no momento (ver core/robo.py)."""
    with _lock:
        conn = _conn()
        c = conn.cursor()
        c.execute(
            """INSERT INTO eventos_trizy (hora, tipo, item_id, placa, texto, screenshot_path)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (time.time(), tipo, item_id, placa, texto, screenshot_path),
        )
        conn.commit()
        conn.close()


def listar_eventos_trizy(desde_id=0, limite=200, tipo=None):
    with _lock:
        conn = _conn()
        c = conn.cursor()
        if tipo:
            c.execute(
                """SELECT id, hora, tipo, item_id, placa, texto, screenshot_path
                   FROM eventos_trizy WHERE id > ? AND tipo = ? ORDER BY id DESC LIMIT ?""",
                (desde_id, tipo, limite),
            )
        else:
            c.execute(
                """SELECT id, hora, tipo, item_id, placa, texto, screenshot_path
                   FROM eventos_trizy WHERE id > ? ORDER BY id DESC LIMIT ?""",
                (desde_id, limite),
            )
        rows = c.fetchall()
        conn.close()
        return rows


def limpar_eventos_trizy_antigos(manter_ultimos=500):
    """Evita que a tabela (e a pasta de screenshots) cresça pra sempre —
    mantém só os N eventos mais recentes."""
    with _lock:
        conn = _conn()
        c = conn.cursor()
        c.execute(
            """DELETE FROM eventos_trizy WHERE id NOT IN (
                 SELECT id FROM eventos_trizy ORDER BY id DESC LIMIT ?
               )""",
            (manter_ultimos,),
        )
        conn.commit()
        conn.close()