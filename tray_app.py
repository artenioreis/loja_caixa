"""
tray_app.py - Lançador do Sistema de Caixa NSG com ícone na bandeja do Windows
- Inicia o servidor Flask em background
- Abre o navegador automaticamente
- Fica na bandeja com menu: Abrir, Reiniciar, Sair
"""

import sys
import os
import threading
import webbrowser
import time
import socket

# ── Garante que caminhos de resource funcionem no PyInstaller ──────────────
def resource_path(relative_path):
    """Retorna o caminho absoluto do recurso (compatível com PyInstaller)."""
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath('.'), relative_path)

def get_base_dir():
    """Diretório onde o .exe (ou script) está localizado."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

BASE_DIR = get_base_dir()

# ── Redireciona logs para arquivo (evita crash sem console) ───────────────
log_path = os.path.join(BASE_DIR, 'caixa_nsg.log')
try:
    sys.stdout = open(log_path, 'a', encoding='utf-8', buffering=1)
    sys.stderr = sys.stdout
except Exception:
    pass

# ── Configuração ──────────────────────────────────────────────────────────
HOST = '0.0.0.0'
PORT = 5000
URL  = f'http://127.0.0.1:{PORT}'

# ── Ajusta o sys.path para encontrar app.py e modelos ────────────────────
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# Força o diretório de trabalho para BASE_DIR (necessário para instance/loja.db)
os.chdir(BASE_DIR)

# ── Variável global do servidor ───────────────────────────────────────────
flask_thread = None
servidor_pronto = threading.Event()

def iniciar_flask():
    """Inicia o servidor Flask em uma thread separada."""
    try:
        from app import app, db, init_db
        import sqlalchemy

        with app.app_context():
            db_path = os.path.join(app.instance_path, 'loja.db')
            os.makedirs(app.instance_path, exist_ok=True)
            if not os.path.exists(db_path):
                print(f'[CAIXA NSG] Criando banco de dados em {db_path}...')
                init_db()

        # Sinaliza que está pronto antes de bloquear no serve
        servidor_pronto.set()
        print(f'[CAIXA NSG] Servidor iniciado em {URL}')

        app.run(
            host=HOST,
            port=PORT,
            debug=False,
            threaded=True,
            use_reloader=False,
        )
    except Exception as e:
        print(f'[CAIXA NSG] ERRO ao iniciar Flask: {e}')
        servidor_pronto.set()   # libera a espera mesmo em erro

def esperar_servidor():
    """Aguarda o servidor estar aceitando conexões TCP."""
    for _ in range(30):          # tenta por até 15 segundos
        try:
            with socket.create_connection(('127.0.0.1', PORT), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.5)
    return False

def abrir_navegador(_=None):
    """Abre o navegador na URL do sistema."""
    webbrowser.open(URL)

def sair_sistema(icon, _=None):
    """Encerra a bandeja e o processo inteiro."""
    print('[CAIXA NSG] Encerrando...')
    icon.stop()
    os._exit(0)

def criar_tray():
    """Cria e executa o ícone na bandeja do Windows."""
    import pystray
    from PIL import Image

    # Carrega o ícone
    icon_path = resource_path(os.path.join('static', 'images', 'tray_icon.png'))
    try:
        img = Image.open(icon_path).resize((64, 64))
    except Exception:
        # Fallback: cria um ícone simples verde se a imagem não for encontrada
        img = Image.new('RGB', (64, 64), color=(15, 23, 42))

    menu = pystray.Menu(
        pystray.MenuItem('🖥️  Abrir Sistema de Caixa', abrir_navegador, default=True),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem('❌  Fechar', sair_sistema),
    )

    icon = pystray.Icon(
        name='CaixaNSG',
        icon=img,
        title='Sistema de Caixa NSG',
        menu=menu,
    )
    return icon

# ── PONTO DE ENTRADA ──────────────────────────────────────────────────────
if __name__ == '__main__':
    print('[CAIXA NSG] Iniciando...')

    # 1. Inicia o Flask em thread daemon
    flask_thread = threading.Thread(target=iniciar_flask, daemon=True)
    flask_thread.start()

    # 2. Aguarda servidor estar pronto (máx 15s)
    print('[CAIXA NSG] Aguardando servidor...')
    servidor_pronto.wait(timeout=15)
    if esperar_servidor():
        print(f'[CAIXA NSG] Servidor OK. Abrindo navegador...')
        webbrowser.open(URL)
    else:
        print('[CAIXA NSG] Servidor demorou a responder. Abrindo mesmo assim...')
        webbrowser.open(URL)

    # 3. Cria e inicia o ícone na bandeja (bloqueia até sair)
    icon = criar_tray()
    icon.run()
