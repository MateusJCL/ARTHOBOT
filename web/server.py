# ==========================================
# WEB/SERVER.PY - Servidor local do ATROPBOT.
# ==========================================
import csv
import io
import json
import sys
import os
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, jsonify, request, render_template, Response

import core.db as db
from core.estado import Maquina, LogBus, Status
from core.robo import RoboAtropbot, SessaoNavegador, abrir_navegador_manual, STATUS_CTR_INVALIDO

app = Flask(__name__)
db.setup_db()

db.limpar_fila_completa()

maquina = Maquina()
log_bus = LogBus()
sessao_navegador = SessaoNavegador(maquina)
robo_thread_ativa = {"thread": None}
navegador_manual_thread_ativa = {"thread": None}

STATUS_DE_ERRO = ("Erro", "Erro Composição", "Sem CTR", STATUS_CTR_INVALIDO, "Erro Data")

def _robo_rodando():
    # Agora a UI verifica se a máquina central está processando algo, e não só a thread solta
    return maquina.status() != Status.PARADO

@app.route("/")
def index():
    return render_template("index.html")

# ==========================================
# VEÍCULOS
# ==========================================
@app.route("/api/veiculos", methods=["GET"])
def api_listar_veiculos():
    rows = db.listar_veiculos()
    return jsonify([{"placa": p, "motorista": m, "cpf": c} for p, m, c in rows])

@app.route("/api/veiculos", methods=["POST"])
def api_salvar_veiculo():
    dados = request.get_json(force=True)
    placa = (dados.get("placa") or "").strip().upper()
    motorista = (dados.get("motorista") or "").strip().upper()
    cpf = (dados.get("cpf") or "").strip()
    placa_original = (dados.get("placa_original") or "").strip().upper()

    if not placa or not cpf:
        return jsonify({"erro": "Placa e CPF são obrigatórios."}), 400

    if placa_original:
        db.editar_veiculo(placa_original, placa, motorista, cpf)
    else:
        db.salvar_veiculo(placa, motorista, cpf)
    return jsonify({"ok": True})

@app.route("/api/veiculos/excluir", methods=["POST"])
def api_excluir_veiculos():
    dados = request.get_json(force=True)
    placas = dados.get("placas") or []
    db.excluir_veiculos(placas)
    return jsonify({"ok": True})

@app.route("/api/veiculos/importar_csv", methods=["POST"])
def api_importar_csv():
    arquivo = request.files.get("arquivo")
    if not arquivo:
        return jsonify({"erro": "Nenhum arquivo enviado."}), 400
    try:
        conteudo = arquivo.read().decode("utf-8-sig")
        leitor = csv.reader(io.StringIO(conteudo), delimiter=",")
        next(leitor, None)
        linhas = []
        for linha in leitor:
            if len(linha) >= 3:
                linhas.append((linha[0].strip(), linha[1].strip(), linha[2].strip()))
        contador = db.importar_veiculos_csv(linhas)
        return jsonify({"ok": True, "importados": contador})
    except Exception as e:
        return jsonify({"erro": f"Erro ao ler arquivo: {e}"}), 400

# ==========================================
# VÍNCULO FAZENDA -> CONTRATO (UNIFICADO)
# ==========================================
@app.route("/api/vinculos", methods=["GET"])
def api_listar_vinculos():
    rows = db.listar_vinculos_fazenda_contrato()
    return jsonify([{"fazenda": f, "contrato": c} for f, c in rows])

@app.route("/api/vinculos", methods=["POST"])
def api_salvar_vinculo():
    dados = request.get_json(force=True)
    fazenda = (dados.get("fazenda") or "").strip().upper()
    contrato = (dados.get("contrato") or "").strip().upper()
    if not fazenda or not contrato:
        return jsonify({"erro": "Preencha Fazenda e Contrato."}), 400
    
    db.salvar_vinculo_fazenda_contrato(fazenda, contrato)
    return jsonify({"ok": True})

@app.route("/api/vinculos/excluir", methods=["POST"])
def api_excluir_vinculo():
    dados = request.get_json(force=True)
    pares = [(p["fazenda"], p["contrato"]) for p in (dados.get("pares") or [])]
    db.excluir_vinculos_fazenda_contrato(pares)
    return jsonify({"ok": True})

@app.route("/api/contratos_da_fazenda")
def api_contratos_da_fazenda():
    fazenda = (request.args.get("fazenda") or "").strip().upper()
    return jsonify(db.contratos_da_fazenda(fazenda))

# ==========================================
# AUTOCOMPLETE
# ==========================================
@app.route("/api/sugestoes")
def api_sugestoes():
    tabela = request.args.get("tabela", "")
    coluna = request.args.get("coluna", "")
    texto = (request.args.get("texto") or "").strip().upper()
    try:
        resultados = db.sugestoes(tabela, coluna, texto)
    except ValueError as e:
        return jsonify({"erro": str(e)}), 400
    return jsonify(resultados)

@app.route("/api/cpf_por_placa")
def api_cpf_por_placa():
    placa = (request.args.get("placa") or "").strip().upper()
    cpf = db.buscar_cpf_por_placa(placa)
    return jsonify({"cpf": cpf or ""})

# ==========================================
# CREDENCIAIS TRIZY
# ==========================================
@app.route("/api/credenciais_trizy", methods=["GET"])
def api_obter_credenciais():
    email, senha = db.obter_credenciais_trizy()
    return jsonify({"email": email, "senha": senha})

@app.route("/api/credenciais_trizy", methods=["POST"])
def api_salvar_credenciais():
    dados = request.get_json(force=True)
    email = (dados.get("email") or "").strip()
    senha = (dados.get("senha") or "").strip()
    db.salvar_credenciais_trizy(email, senha)
    return jsonify({"ok": True})

# ==========================================
# FILA (persistida)
# ==========================================
@app.route("/api/contratos", methods=["GET"])
def api_listar_contratos_todos():
    return jsonify(db.sugestoes("contratos", "numero", ""))

@app.route("/api/fila", methods=["GET"])
def api_listar_fila():
    rows = db.listar_fila_com_indice_lote()
    return jsonify([
        {"id": i, "terminal": t, "fazenda": f, "contrato": c, "placa": p, "cpf": cpf, "status": s, "indice_lote": idx}
        for i, t, f, c, p, cpf, s, idx in rows
    ])

@app.route("/api/fila", methods=["POST"])
def api_adicionar_fila():
    dados = request.get_json(force=True)
    terminal = (dados.get("terminal") or "").strip()
    fazenda = (dados.get("fazenda") or "").strip().upper()
    contrato = (dados.get("contrato") or "").strip().upper()
    placa = (dados.get("placa") or "").strip().upper()
    cpf = (dados.get("cpf") or "").strip()

    if not all([terminal, fazenda, contrato]):
        return jsonify({"erro": "Preencha os dados do Lote (Terminal, Fazenda e CTR) antes de adicionar veículos."}), 400
    if not all([placa, cpf]):
        return jsonify({"erro": "Preencha CPF e Placa."}), 400

    db.salvar_vinculo_fazenda_contrato(fazenda, contrato)
    item_id = db.adicionar_item_fila(terminal, fazenda, contrato, placa, cpf)
    # Reorganiza automaticamente: agrupa por Terminal/Fazenda/Contrato,
    # para o robô trocar de lote o mínimo de vezes possível ao processar.
    db.reorganizar_fila_por_lote()
    db.registrar_log_geral(f"Veículo {placa} adicionado à fila (Terminal: {terminal} | CTR: {contrato}).")
    return jsonify({"ok": True, "id": item_id})

@app.route("/api/fila/reorganizar", methods=["POST"])
def api_reorganizar_fila():
    """Permite reorganizar manualmente (ex.: depois de remover itens, ou
    se quiser reagrupar de novo após qualquer edição)."""
    if _robo_rodando():
        return jsonify({"erro": "Não é possível reorganizar enquanto o ATROPBOT está em execução."}), 400
    db.reorganizar_fila_por_lote()
    return jsonify({"ok": True})

@app.route("/api/fila/remover", methods=["POST"])
def api_remover_fila():
    dados = request.get_json(force=True)
    ids = dados.get("ids") or []
    if _robo_rodando() and maquina.item_atual_id in ids:
        return jsonify({"erro": "Não é possível remover o item que está sendo processado agora."}), 400
    db.remover_itens_fila(ids)
    return jsonify({"ok": True})

@app.route("/api/fila/limpar", methods=["POST"])
def api_limpar_fila():
    if _robo_rodando():
        return jsonify({"erro": "Não é possível limpar enquanto o ATROPBOT está em execução. Pause ou aguarde finalizar."}), 400
    db.limpar_fila_completa()
    return jsonify({"ok": True})

@app.route("/api/fila/log/<int:item_id>")
def api_log_item(item_id):
    rows = db.listar_log_item(item_id)
    return jsonify([{"hora": h, "mensagem": m} for h, m in rows])

# ==========================================
# CONTROLE DO ROBÔ E PROTEÇÃO DE NAVEGADOR
# ==========================================
def _disparar_robo(itens_fila, modo_guiado):
    robo = RoboAtropbot(maquina, log_bus, modo_guiado=modo_guiado)
    t = threading.Thread(target=robo.executar, args=(itens_fila, sessao_navegador), daemon=True)
    robo_thread_ativa["thread"] = t
    t.start()

@app.route("/api/robo/iniciar", methods=["POST"])
def api_iniciar_robo():
    if _robo_rodando():
        return jsonify({"erro": "O ATROPBOT já está rodando."}), 400
        
    # TRAVA BLINDADA: Exige fechar o Chrome antes de rodar a fila!
    if sessao_navegador.esta_viva():
        return jsonify({"erro": "O navegador da execução anterior ainda está aberto. Feche a janela do Chrome no 'X' antes de iniciar."}), 400

    dados = request.get_json(force=True) or {}
    modo_guiado = bool(dados.get("modo_guiado", False))

    todos = db.listar_fila()
    if not todos:
        return jsonify({"erro": "Adicione veículos na fila primeiro."}), 400

    pendentes = [row for row in todos if row[6] != "Sucesso"]
    if not pendentes:
        return jsonify({"erro": "Todos os veículos da fila já estão com status Sucesso."}), 400

    itens_fila = [tuple(row) for row in todos]
    db.registrar_log_geral("--- INICIANDO ATROPBOT (sequencial) ---")
    _disparar_robo(itens_fila, modo_guiado)
    return jsonify({"ok": True})

@app.route("/api/robo/reprocessar_erros", methods=["POST"])
def api_reprocessar_erros():
    if _robo_rodando():
        return jsonify({"erro": "O ATROPBOT já está rodando."}), 400

    if sessao_navegador.esta_viva():
        return jsonify({"erro": "O navegador da execução anterior ainda está aberto. Feche a janela do Chrome no 'X' antes de continuar."}), 400

    dados = request.get_json(force=True) or {}
    modo_guiado = bool(dados.get("modo_guiado", False))

    todos = db.listar_fila()
    itens_com_erro = [row for row in todos if row[6] in STATUS_DE_ERRO]
    if not itens_com_erro:
        return jsonify({"erro": "Não há itens com erro na fila para reprocessar."}), 400

    itens_para_reprocessar = []
    for item_id, terminal, fazenda, contrato, placa, cpf, status in itens_com_erro:
        db.atualizar_status_item(item_id, "Aguardando...")
        itens_para_reprocessar.append((item_id, terminal, fazenda, contrato, placa, cpf, "Aguardando..."))

    db.registrar_log_geral(f"Reprocessando {len(itens_para_reprocessar)} item(ns) com erro...")
    _disparar_robo(itens_para_reprocessar, modo_guiado)
    return jsonify({"ok": True, "quantidade": len(itens_para_reprocessar)})

@app.route("/api/robo/reprocessar_item", methods=["POST"])
def api_reprocessar_item():
    if _robo_rodando():
        return jsonify({"erro": "O ATROPBOT já está rodando."}), 400
        
    if sessao_navegador.esta_viva():
        return jsonify({"erro": "O navegador da execução anterior ainda está aberto. Feche a janela do Chrome no 'X' antes de continuar."}), 400

    dados = request.get_json(force=True)
    item_id = dados.get("id")
    modo_guiado = bool(dados.get("modo_guiado", False))

    row = db.buscar_item_fila(item_id)
    if row is None:
        return jsonify({"erro": "Item não encontrado na fila."}), 404
    _, terminal, fazenda, contrato, placa, cpf, status = row
    if status == "Sucesso":
        return jsonify({"erro": f"O veículo {placa} já está com status Sucesso."}), 400

    db.atualizar_status_item(item_id, "Aguardando...")
    db.registrar_log_geral(f"Reprocessando individualmente: {placa}...")
    _disparar_robo([(item_id, terminal, fazenda, contrato, placa, cpf, "Aguardando...")], modo_guiado)
    return jsonify({"ok": True})

@app.route("/api/robo/pausar", methods=["POST"])
def api_pausar_robo():
    if not _robo_rodando():
        return jsonify({"erro": "O ATROPBOT não está em execução."}), 400
    if maquina.status() != Status.RODANDO:
        return jsonify({"erro": "Não é possível pausar manualmente agora."}), 400
    maquina.pausar_manual()
    db.registrar_log_geral("⏸ Pausado pelo usuário. Clique em Retomar para continuar.")
    return jsonify({"ok": True})

@app.route("/api/robo/retomar", methods=["POST"])
def api_retomar_robo():
    if maquina.status() != Status.PAUSADO_MANUAL:
        return jsonify({"erro": "Não há uma pausa manual ativa para retomar."}), 400
    maquina.retomar_manual()
    db.registrar_log_geral("▶ Retomado pelo usuário.")
    return jsonify({"ok": True})

@app.route("/api/robo/cancelar", methods=["POST"])
def api_cancelar_robo():
    if not _robo_rodando():
        return jsonify({"erro": "O ATROPBOT não está em execução."}), 400
    maquina.cancelar()
    db.registrar_log_geral("Execução cancelada pelo usuário. Navegador permanece aberto.")
    return jsonify({"ok": True})

@app.route("/api/robo/resolver_ctr", methods=["POST"])
def api_resolver_ctr():
    dados = request.get_json(force=True)
    pular_lote = bool(dados.get("pular_lote", False))
    ctx = maquina.resolver_ctr(pular_lote)
    if ctx is None:
        return jsonify({"erro": "Não há pausa por CTR ativa."}), 400
    return jsonify({"ok": True})

@app.route("/api/robo/resolver_navegador_fechado", methods=["POST"])
def api_resolver_navegador_fechado():
    dados = request.get_json(force=True)
    cancelar = bool(dados.get("cancelar", False))

    if maquina.status() != Status.PAUSADO_NAVEGADOR:
        return jsonify({"erro": "Não há pausa por navegador fechado ativa."}), 400

    maquina.resolver_navegador_fechado(cancelar=cancelar)
    return jsonify({"ok": True})

@app.route("/api/robo/resolver_erro_trizy", methods=["POST"])
def api_resolver_erro_trizy():
    dados = request.get_json(force=True)
    cancelar = bool(dados.get("cancelar", False))

    if maquina.status() != Status.PAUSADO_ERRO_TRIZY:
        return jsonify({"erro": "Não há pausa por aviso do Trizy ativa."}), 400

    maquina.resolver_erro_trizy(cancelar=cancelar)
    return jsonify({"ok": True})

@app.route("/api/robo/continuar_checkpoint", methods=["POST"])
def api_continuar_checkpoint():
    maquina.continuar_checkpoint_guiado()
    return jsonify({"ok": True})

@app.route("/api/robo/modo_guiado", methods=["POST"])
def api_definir_modo_guiado():
    dados = request.get_json(force=True)
    ativo = bool(dados.get("ativo", False))
    maquina.modo_guiado = ativo
    db.registrar_log_geral(f"Modo Guiado {'ativado' if ativo else 'desativado'}." )
    return jsonify({"ok": True})

@app.route("/api/robo/estado")
def api_estado_robo():
    snap = maquina.snapshot()
    snap["rodando"] = _robo_rodando()
    snap["navegador_aberto"] = sessao_navegador.esta_viva()
    return jsonify(snap)

@app.route("/api/navegador/abrir_manual", methods=["POST"])
def api_abrir_navegador_manual():
    if _robo_rodando():
        return jsonify({"erro": "O ATROPBOT já está rodando com o navegador aberto."}), 400
    if sessao_navegador.esta_viva():
        return jsonify({"erro": "O navegador já está aberto. Feche a janela atual no 'X' antes de abrir uma nova."}), 400

    def _executar():
        abrir_navegador_manual(maquina, log_bus, sessao_navegador)

    novo_t = threading.Thread(target=_executar, daemon=True)
    navegador_manual_thread_ativa["thread"] = novo_t
    novo_t.start()
    db.registrar_log_geral("Abrindo navegador (modo manual, sem rodar a fila)...")
    return jsonify({"ok": True})

@app.route("/api/navegador/forcar_fechamento", methods=["POST"])
def api_forcar_fechamento_navegador():
    """'Tirar o plugue da tomada' — zera o estado do navegador na força,
    para os casos em que a detecção automática (evento de fechamento ou
    a checagem ativa em esta_viva()) não acompanhou a realidade, por
    qualquer motivo (Chrome fechado com 'Finalizar tarefa', travamento
    do sistema, etc.). Não falha mesmo se o robô estiver 'rodando' —
    pelo contrário, é pensado justamente para destravar esse caso."""
    if _robo_rodando():
        maquina.cancelar()
        db.registrar_log_geral("Execução cancelada (fechamento forçado do navegador solicitado).")
    sessao_navegador.forcar_fechamento()
    db.registrar_log_geral("🔌 Navegador desconectado na força pelo usuário.")
    return jsonify({"ok": True})

# ==========================================
# LOG
# ==========================================
@app.route("/api/log_geral")
def api_log_geral():
    desde_id = request.args.get("desde_id", 0, type=int)
    rows = db.listar_log_geral(desde_id)
    return jsonify([{"id": i, "hora": h, "mensagem": m} for i, h, m in rows])

# ==========================================
# EVENTOS DO TRIZY (captura genérica de tela: erros, sucessos, avisos)
# ==========================================
@app.route("/api/eventos_trizy")
def api_listar_eventos_trizy():
    desde_id = request.args.get("desde_id", 0, type=int)
    tipo = request.args.get("tipo") or None
    rows = db.listar_eventos_trizy(desde_id=desde_id, tipo=tipo)
    return jsonify([
        {"id": i, "hora": h, "tipo": t, "item_id": iid, "placa": p, "texto": txt, "screenshot": shot}
        for i, h, t, iid, p, txt, shot in rows
    ])

@app.route("/screenshots/<path:nome_arquivo>")
def servir_screenshot(nome_arquivo):
    from flask import send_from_directory
    from core.robo import PASTA_SCREENSHOTS
    return send_from_directory(PASTA_SCREENSHOTS, nome_arquivo)

@app.route("/api/eventos")
def api_eventos_sse():
    fila = log_bus.assinar()
    def stream():
        try:
            while True:
                if fila:
                    evento = fila.pop(0)
                    yield f"data: {json.dumps(evento)}\n\n"
                else:
                    time.sleep(0.3)
                    yield ": ping\n\n"
        finally:
            log_bus.cancelar_assinatura(fila)

    return Response(stream(), mimetype="text/event-stream")

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8765, debug=False, threaded=True)