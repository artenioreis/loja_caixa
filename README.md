# Sistema de Caixa (PDV) - Loja Caixa

![Python](https://img.shields.io/badge/Python-3.11+-blue?logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-2.3.3-black?logo=flask&logoColor=white)
![Bootstrap](https://img.shields.io/badge/Bootstrap-5.1-purple?logo=bootstrap&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-3-blue?logo=sqlite&logoColor=white)

Um sistema de Ponto de Venda (PDV) completo e responsivo, desenvolvido em Python com o micro-framework Flask. O projeto é focado na simplicidade e em fornecer as funcionalidades essenciais para a gestão de vendas e caixa de pequenos comércios.

Este repositório foi customizado para a **Paróquia Nossa Senhora das Graças, Pirambu**, incluindo o logotipo da instituição e informações de endereço no cupom de venda.

## 🚀 Funcionalidades Principais

O sistema é dividido em dois perfis de acesso (Administrador e Caixa), cada um com suas permissões específicas.

### Funcionalidades Gerais (Admin e Caixa)
* **Autenticação Segura:** Sistema de login com hash de senhas.
* **Controle de Caixa:** Fluxo completo de Abertura de Caixa (com saldo inicial) e Fechamento de Caixa (com conferência de valores).
* **PDV (Ponto de Venda):** Tela de vendas dinâmica:
    * Busca de produtos por Código de Barras ou ID do produto.
    * Visualização da imagem do produto durante a busca.
    * Carrinho de compras interativo (adicionar, remover itens).
    * Atalhos de teclado (`Enter` para adicionar, `F6` para finalizar, `F3` para cancelar).
* **Finalização de Venda:** Modal de pagamento com suporte a:
    * Dinheiro (com cálculo de troco).
    * Cartão.
    * PIX (exibe um QR Code estático para o cliente escanear).
* **Impressão de Cupom:** Geração de um cupom não-fiscal formatado para impressão térmica.
* **Interface Responsiva:** O sistema se adapta a Desktops, Tablets e Celulares.
* **Menu Colapsável:** O menu lateral pode ser ocultado para maximizar o espaço da tela.

### Funcionalidades de Administrador
* **Dashboard:** Painel com estatísticas rápidas (Vendas do dia, produtos com estoque baixo, etc.).
* **Gestão de Produtos:** CRUD completo (Criar, Ler, Editar, Desativar) de produtos.
* **Upload de Imagens:** Suporte a upload de imagem de produto no cadastro.
* **Gestão de Usuários:** CRUD completo (Criar, Ler, Editar, Desativar) de usuários e seus perfis de acesso.
* **Relatórios de Vendas:** Página de relatórios com filtros avançados por:
    * Período (Data de Início e Fim).
    * Operador de Caixa.
    * Forma de Pagamento.

## 🛠️ Tecnologias Utilizadas

* **Backend:**
    * **Python 3**
    * **Flask:** Micro-framework web.
    * **Flask-SQLAlchemy:** ORM para manipulação do banco de dados.
    * **Flask-Login:** Gerenciamento de sessão e autenticação de usuários.
    * **Werkzeug:** Hash de senhas e upload de arquivos.
* **Frontend:**
    * **HTML5** e **CSS3**.
    * **Bootstrap 5:** Framework CSS para design responsivo (utilizado via CDN).
    * **Vanilla JavaScript:** Utilizado para toda a interatividade do PDV (Fetch API, manipulação de DOM).
    * **Jinja2:** Template engine do Flask.
    * **Font Awesome:** Biblioteca de ícones (utilizada via CDN).
* **Banco de Dados:**
    * **SQLite:** Banco de dados leve, ideal para aplicações locais e de pequeno porte.

## ⚙️ Instalação e Execução

Siga os passos abaixo para executar o projeto localmente.

1.  **Clone o repositório:**
    ```bash
    git clone [https://github.com/seu-usuario/loja_caixa.git](https://github.com/seu-usuario/loja_caixa.git)
    cd loja_caixa
    ```

2.  **Crie e ative um ambiente virtual (venv):**
    ```bash
    # Windows
    python -m venv venv
    .\venv\Scripts\activate
    
    # macOS/Linux
    python3 -m venv venv
    source venv/bin/activate
    ```

3.  **Instale as dependências:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Execute a aplicação:**
    ```bash
    python app.py
    ```
    O sistema será iniciado no modo de *debug*. A primeira execução irá criar automaticamente o banco de dados `loja.db` e popular com dados de exemplo (usuários e produtos).

5.  **Acesse o sistema:**
    Abra seu navegador e acesse: `http://127.0.0.1:5000`

## 🔑 Credenciais de Teste

O banco de dados é inicializado com dois usuários padrão:

* **Administrador:**
    * **Email:** `admin@loja.com`
    * **Senha:** `admin123`
* **Caixa:**
    * **Email:** `caixa@loja.com`
    * **Senha:** `caixa123`

## 🎨 Customização (Logo e PIX)

Para alterar o logo da empresa e o QR Code do PIX, basta substituir os arquivos na pasta `static/images/`:

* **Logo:** `static/images/logo_empresa.png`
* **QR Code PIX:** `static/images/qrcode_pix_loja.png`

---
