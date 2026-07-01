# ==========================================
# APP.PY - Ponto de entrada do ATROPBOT (Versão Desktop Nativo)
# ==========================================
import threading
import webview
from web.server import app

URL = "http://127.0.0.1:8765"

def iniciar_servidor():
    # threaded=True é essencial: sem isso, o Flask processa só UMA
    # requisição por vez. Como /api/robo/estado faz uma chamada real ao
    # Playwright (esta_viva() lê page.url), qualquer lentidão nessa
    # chamada travava a interface inteira — inclusive o próprio polling
    # que deveria corrigir o status, parecendo que o app "nunca atualiza".
    app.run(host="127.0.0.1", port=8765, debug=False, use_reloader=False, threaded=True)

if __name__ == "__main__":
    # 1. Inicia o backend (Flask) silenciosamente no fundo
    t = threading.Thread(target=iniciar_servidor, daemon=True)
    t.start()
    
    # 2. Abre a interface numa Janela de App Nativa (sem barra de URL do Chrome)
    webview.create_window(
        title="ATROPBOT — Orquestrador Logístico", 
        url=URL, 
        width=1100, 
        height=720,
        min_size=(900, 600)
    )
    webview.start()