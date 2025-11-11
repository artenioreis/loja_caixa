import subprocess
import webbrowser
import time
import os

try:
    # 1. Defina o caminho raiz do seu projeto
    # (Use 'r' para 'raw string' e evitar problemas com barras invertidas)
    caminho_projeto = r"C:\CAIXA_NSG"

    # 2. Defina os caminhos para o Python do venv e para o seu app.py
    # (Baseado na estrutura do seu .bat e app.py)
    caminho_python_venv = os.path.join(caminho_projeto, ".venv", "Scripts", "python.exe")
    caminho_app_py = os.path.join(caminho_projeto, "app.py")

    # Verifica se os arquivos essenciais existem
    if not os.path.exists(caminho_python_venv):
        raise FileNotFoundError(f"Python do venv não encontrado em: {caminho_python_venv}")
    if not os.path.exists(caminho_app_py):
        raise FileNotFoundError(f"app.py não encontrado em: {caminho_app_py}")

    # 3. Comando para iniciar o servidor Flask (usando o Python do venv)
    comando = [caminho_python_venv, caminho_app_py]

    print("Iniciando o servidor Flask...")
    # Inicia o servidor em um novo processo de console
    # O 'cwd' garante que o app.py encontre o 'instance/loja.db'
    servidor_processo = subprocess.Popen(
        comando, 
        cwd=caminho_projeto, 
        creationflags=subprocess.CREATE_NEW_CONSOLE
    )

    # 4. Aguarde alguns segundos para o servidor iniciar
    print("Aguardando 5 segundos...")
    time.sleep(5)

    # 5. Abra o navegador no endereço correto
    url = "http://127.0.0.1:5000"
    print(f"Abrindo o navegador em {url}...")
    webbrowser.open(url)

except Exception as e:
    # Se algo der errado, exibe um pop-up de erro simples
    # (Útil já que o console do launcher não será visível)
    import ctypes
    ctypes.windll.user32.MessageBoxW(0, f"Ocorreu um erro ao iniciar:\n\n{e}", "Erro no Caixa Festa", 0x10)