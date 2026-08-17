from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from database import db
from sqlalchemy import func, or_ # <-- IMPORTAÇÃO ADICIONADA
from models import Usuario, Produto, Venda, ItemVenda, MovimentoCaixa, Configuracao, MovimentoEstoque
# Importações de data/hora atualizadas (agora usando APENAS HORA LOCAL)
from datetime import datetime, timedelta, date, time
import os
# NOVAS IMPORTAÇÕES PARA UPLOAD E NOME DE ARQUIVO SEGURO
from werkzeug.utils import secure_filename

# =======================================================
#               INÍCIO DAS NOVAS IMPORTAÇÕES (EXCEL)
# =======================================================
import pandas as pd
import io
from flask import make_response
# =======================================================
#                FIM DAS NOVAS IMPORTAÇÕES
# =======================================================


# --- CONFIGURAÇÕES DE UPLOAD ---
# Caminho relativo (a partir da raiz do app) para servir os arquivos
UPLOAD_FOLDER_REL = 'static/uploads/produtos'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

def allowed_file(filename):
    """Verifica se a extensão do arquivo é permitida"""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS
# -------------------------------


def create_app():
    """
    Função factory para criar a aplicação Flask
    """
    app = Flask(__name__)
    
    # =========================================================
    # CONFIGURAÇÕES PARA REDE MULTI-PDV
    # =========================================================
    # SECRET_KEY fixa e forte — sessões sobrevivem a reinicializações
    app.config['SECRET_KEY'] = 'NSG@2025#CaixaSeguro!K9mXpQrZ'

    # SQLite com WAL mode para suportar leituras simultâneas de múltiplos PDVs
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///loja.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # Pool de conexões: permite múltiplas conexões simultâneas sem timeout
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'connect_args': {
            'check_same_thread': False,   # Permite uso em múltiplas threads
            'timeout': 30,                # Aguarda até 30s se o banco estiver ocupado
        },
        'pool_size': 10,                  # Conexões simultâneas no pool
        'max_overflow': 20,               # Conexões extras em pico
        'pool_timeout': 30,               # Timeout para obter conexão do pool
        'pool_recycle': 1800,             # Recicla conexões a cada 30 min
        'pool_pre_ping': True,            # Verifica conexão antes de usar
    }

    # Sessão permanente por 8 horas (turno de trabalho)
    from datetime import timedelta
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=8)
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    app.config['SESSION_COOKIE_SECURE'] = False  # True se usar HTTPS
    
    # --- CONFIGURAÇÕES DE UPLOAD ---
    # Caminho absoluto para salvar os arquivos
    UPLOAD_FOLDER_ABS = os.path.join(app.root_path, UPLOAD_FOLDER_REL)
    app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER_ABS
    app.config['UPLOAD_FOLDER_REL'] = UPLOAD_FOLDER_REL # Salva o relativo para usar nos templates
    
    # Cria o diretório de uploads se não existir
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    # -------------------------------

    # Inicializações
    db.init_app(app)

    # Ativa WAL mode no SQLite ao criar conexão (melhora concorrência multi-PDV)
    from sqlalchemy import event
    from sqlalchemy.engine import Engine
    import sqlite3

    @event.listens_for(Engine, 'connect')
    def set_sqlite_pragma(dbapi_connection, connection_record):
        if isinstance(dbapi_connection, sqlite3.Connection):
            cursor = dbapi_connection.cursor()
            cursor.execute('PRAGMA journal_mode=WAL')    # Write-Ahead Logging
            cursor.execute('PRAGMA synchronous=NORMAL')  # Balanço velocidade/segurança
            cursor.execute('PRAGMA cache_size=-64000')   # Cache de 64MB
            cursor.execute('PRAGMA foreign_keys=ON')     # Integridade referencial
            cursor.execute('PRAGMA busy_timeout=30000')  # 30s de espera em lock
            cursor.close()
    
    return app

# Cria a aplicação
app = create_app()

# Configuração do Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Por favor, faça login para acessar esta página.'

@login_manager.user_loader
def load_user(user_id):
    """Carrega o usuário a partir do ID na sessão"""
    # CORREÇÃO: Usando a nova sintaxe do SQLAlchemy
    return db.session.get(Usuario, int(user_id))

# =============================================================================
# FUNÇÃO AUXILIAR PARA VERIFICAR CAIXA ABERTO
# =============================================================================

def get_caixa_aberto():
    """Retorna se o caixa está aberto para o usuário atual"""
    if not current_user.is_authenticated:
        return False, None
    
    movimento_atual = MovimentoCaixa.query.filter_by(
        usuario_id=current_user.id, 
        status='aberto'
    ).first()
    
    return movimento_atual is not None, movimento_atual

# =============================================================================
# ROTAS DE AUTENTICAÇÃO
# =============================================================================

@app.route('/')
def index():
    """Página inicial - redireciona para login ou dashboard"""
    if current_user.is_authenticated:
        # Se for admin, vai pro dashboard
        if current_user.is_admin():
            return redirect(url_for('dashboard'))
        # Se for caixa, vai direto pras vendas
        return redirect(url_for('vendas'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    """
    Rota para login de usuários
    """
    # Se o usuário já está logado, redireciona para o dashboard
    if current_user.is_authenticated:
        if current_user.is_admin():
            return redirect(url_for('dashboard'))
        return redirect(url_for('vendas'))
    
    if request.method == 'POST':
        email = request.form.get('email')
        senha = request.form.get('senha')
        
        # Busca usuário pelo email
        usuario = Usuario.query.filter_by(email=email, ativo=True).first()
        
        # Verifica se usuário existe e senha está correta
        if usuario and usuario.check_senha(senha):
            login_user(usuario)
            
            # Redireciona para a página que tentava acessar ou dashboard/vendas
            next_page = request.args.get('next')
            if next_page:
                return redirect(next_page)
            
            if current_user.is_admin():
                return redirect(url_for('dashboard'))
            else:
                return redirect(url_for('vendas'))
        else:
            flash('Email ou senha incorretos!', 'danger')
    
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    """Rota para logout do usuário"""
    logout_user()
    flash('Logout realizado com sucesso!', 'info')
    return redirect(url_for('login'))

# =============================================================================
# MIDDLEWARES E FUNÇÕES AUXILIARES
# =============================================================================

def get_config(chave, default=''):
    conf = Configuracao.query.filter_by(chave=chave).first()
    return conf.valor if conf else default

def set_config(chave, valor):
    conf = Configuracao.query.filter_by(chave=chave).first()
    if conf:
        conf.valor = str(valor)
    else:
        conf = Configuracao(chave=chave, valor=str(valor))
        db.session.add(conf)
    db.session.commit()

@app.context_processor
def inject_context():
    """
    Injeta variáveis em todos os templates
    """
    caixa_aberto = False
    movimento_atual = None
    
    if current_user.is_authenticated:
        caixa_aberto, movimento_atual = get_caixa_aberto()
    
    # ===========================================================
    #           CORREÇÃO DE FUSO (VISUAL)
    # ===========================================================
    # Voltando para datetime.now() para usar a HORA LOCAL
    orcamento_ativo = get_config('orcamento_ativo', 'True') == 'True'
    
    # Configurações dinâmicas de Logo e Cupom
    logo_empresa = get_config('logo_empresa', 'images/logo_empresa.png')
    cupom_linha1 = get_config('cupom_linha1', 'Paróquia Nossa Senhora das Graças,')
    cupom_linha2 = get_config('cupom_linha2', 'Pirambu')
    cupom_linha3 = get_config('cupom_linha3', 'Rua Nossa Senhora das Graças, 255')
    cupom_linha4 = get_config('cupom_linha4', 'CNPJ: 07.210.925/0014-20')
    
    return dict(
        caixa_aberto=caixa_aberto,
        movimento_atual=movimento_atual,
        now=datetime.now(), # <-- CORRIGIDO
        orcamento_ativo=orcamento_ativo,
        logo_empresa=logo_empresa,
        cupom_linha1=cupom_linha1,
        cupom_linha2=cupom_linha2,
        cupom_linha3=cupom_linha3,
        cupom_linha4=cupom_linha4
    )
    # ===========================================================

# =============================================================================
# ROTAS PRINCIPAIS
# =============================================================================

# =============================================================================
#           INÍCIO DA ROTA MODIFICADA (DASHBOARD)
# =============================================================================
@app.route('/dashboard')
@login_required
def dashboard():
    """
    Dashboard principal do sistema (Apenas Admin)
    """
    if not current_user.is_admin():
        flash('Acesso não autorizado!', 'danger')
        return redirect(url_for('vendas'))

    # ===========================================================
    #           CORREÇÃO DE FUSO (Usar HORA LOCAL)
    # ===========================================================
    # Estatísticas para o dashboard
    hoje = date.today() # CORRIGIDO (era datetime.utcnow().date())
    
    # Total vendido hoje
    # Usando func.date para comparar apenas a data
    vendas_hoje = Venda.query.filter(
        db.func.date(Venda.data_venda) == hoje,
        Venda.status == 'finalizada'
    ).all()
    total_hoje = sum(venda.valor_total for venda in vendas_hoje)
    
    # Quantidade de produtos com estoque baixo
    estoque_baixo = Produto.query.filter(
        Produto.estoque_atual <= Produto.estoque_minimo,
        Produto.ativo == True
    ).count()
    
    # Total de produtos ativos
    total_produtos = Produto.query.filter_by(ativo=True).count()
    
    # Movimento de caixa atual (do admin logado)
    caixa_aberto, movimento_atual = get_caixa_aberto()
    
    # Buscar caixas esquecidos
    # (Compara a data de abertura local com o início do dia local)
    hoje_meia_noite_local = datetime.combine(hoje, time.min) # CORRIGIDO
    caixas_esquecidos = MovimentoCaixa.query.filter(
        MovimentoCaixa.status == 'aberto',
        MovimentoCaixa.data_abertura < hoje_meia_noite_local
    ).order_by(MovimentoCaixa.data_abertura.desc()).all()
    # ===========================================================
    #           FIM DA CORREÇÃO DE FUSO
    # ===========================================================
    
    # Status de todos os caixas
    status_caixas = []
    operadores = Usuario.query.filter(
        Usuario.perfil.in_(['caixa', 'admin']),
        Usuario.ativo == True
    ).order_by(Usuario.nome).all()

    for op in operadores:
        ultimo_movimento = MovimentoCaixa.query.filter_by(usuario_id=op.id).order_by(MovimentoCaixa.data_abertura.desc()).first()
        
        if ultimo_movimento:
            diferenca = 0.0
            saldo_esperado = 0.0
            saldo_final_informado = 0.0
            mostrar_diferenca = False
            
            # Se o último movimento está fechado, calcula a diferença
            if ultimo_movimento.status == 'fechado':
                
                # 1. Busca todas as vendas finalizadas do período
                vendas_periodo = Venda.query.filter(
                    Venda.data_venda >= ultimo_movimento.data_abertura,
                    Venda.data_venda <= ultimo_movimento.data_fechamento, 
                    Venda.usuario_id == op.id,
                    Venda.status == 'finalizada'
                ).all()
                
                # 2. Soma apenas o valor_dinheiro (abatendo troco)
                total_vendas_dinheiro = sum((venda.valor_dinheiro - venda.troco) for venda in vendas_periodo)
                
                # 3. Calcula o saldo esperado (Dinheiro)
                #    (Saldo Inicial + Vendas em Dinheiro)
                saldo_esperado = (ultimo_movimento.saldo_inicial or 0) + total_vendas_dinheiro

                # Pega o saldo que foi informado no fechamento
                saldo_final_informado = ultimo_movimento.saldo_final or 0
                
                # Calcula a diferença
                diferenca = saldo_final_informado - saldo_esperado

                # Verifica se a diferença é (praticamente) zero.
                if abs(diferenca) > 0.001:
                    mostrar_diferenca = True
            
            status_caixas.append({
                'nome': op.nome,
                'status': ultimo_movimento.status,
                'data': ultimo_movimento.data_fechamento if ultimo_movimento.status == 'fechado' else ultimo_movimento.data_abertura,
                'diferenca': diferenca,
                'saldo_esperado': saldo_esperado, 
                'saldo_informado': saldo_final_informado,
                'mostrar_diferenca': mostrar_diferenca
            })
        else:
            # Operador nunca abriu um caixa
            status_caixas.append({
                'nome': op.nome,
                'status': 'nunca_aberto',
                'data': None,
                'diferenca': 0.0,
                'saldo_esperado': 0.0,
                'saldo_informado': 0.0,
                'mostrar_diferenca': False
            })

    return render_template('dashboard.html',
                         total_hoje=total_hoje,
                         estoque_baixo=estoque_baixo,
                         total_produtos=total_produtos,
                         movimento_atual=movimento_atual,
                         caixas_esquecidos=caixas_esquecidos,
                         status_caixas=status_caixas)
# =============================================================================
#           FIM DA ROTA MODIFICADA (DASHBOARD)
# =============================================================================

# =============================================================================
# ROTAS DE CONFIGURAÇÕES GERAIS
# =============================================================================

@app.route('/config/toggle_orcamento')
@login_required
def toggle_orcamento():
    if not current_user.is_admin():
        flash('Acesso não autorizado!', 'danger')
        return redirect(url_for('vendas'))
        
    atual = get_config('orcamento_ativo', 'True') == 'True'
    novo_valor = 'False' if atual else 'True'
    set_config('orcamento_ativo', novo_valor)
    
    status_texto = "Ativado" if novo_valor == 'True' else "Desativado"
    flash(f'Módulo de Orçamento {status_texto} com sucesso!', 'success')
    return redirect(url_for('dashboard'))

@app.route('/configuracoes', methods=['GET', 'POST'])
@login_required
def configuracoes():
    """Rota para configurações gerais do sistema (Apenas Admin)"""
    if not current_user.is_admin():
        flash('Acesso não autorizado!', 'danger')
        return redirect(url_for('vendas'))
        
    if request.method == 'POST':
        cupom_linha1 = request.form.get('cupom_linha1', '').strip()
        cupom_linha2 = request.form.get('cupom_linha2', '').strip()
        cupom_linha3 = request.form.get('cupom_linha3', '').strip()
        cupom_linha4 = request.form.get('cupom_linha4', '').strip()
        
        set_config('cupom_linha1', cupom_linha1)
        set_config('cupom_linha2', cupom_linha2)
        set_config('cupom_linha3', cupom_linha3)
        set_config('cupom_linha4', cupom_linha4)
        
        # Lógica de Upload do Logo da Empresa
        if 'logo_file' in request.files:
            file = request.files['logo_file']
            if file and file.filename != '':
                ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
                if ext in {'png', 'jpg', 'jpeg', 'gif', 'webp', 'ico'}:
                    logo_dir = os.path.join(app.root_path, 'static/images')
                    os.makedirs(logo_dir, exist_ok=True)
                    
                    timestamp = int(datetime.now().timestamp())
                    filename = f"logo_config_{timestamp}.{ext}"
                    file_path = os.path.join(logo_dir, filename)
                    
                    # Remover logos customizados antigos
                    for existing_file in os.listdir(logo_dir):
                        if existing_file.startswith('logo_config_'):
                            try:
                                os.remove(os.path.join(logo_dir, existing_file))
                            except Exception:
                                pass
                                
                    file.save(file_path)
                    set_config('logo_empresa', f"images/{filename}")
                else:
                    flash('Extensão de imagem para o logo não permitida. Use PNG, JPG, JPEG, WEBP, GIF ou ICO.', 'danger')
                    
        flash('Configurações atualizadas com sucesso!', 'success')
        return redirect(url_for('configuracoes'))
        
    return render_template('configuracoes.html')

# =============================================================================
# ROTAS DO MÓDULO DE CAIXA
# =============================================================================

@app.route('/caixa/abrir', methods=['GET', 'POST'])
@login_required
def abrir_caixa():
    """
    Rota para abertura de caixa
    """
    # Verifica se já existe caixa aberto
    caixa_aberto, movimento_atual = get_caixa_aberto()
    
    if caixa_aberto:
        flash('Já existe um caixa aberto!', 'warning')
        return redirect(url_for('vendas'))
    
    if request.method == 'POST':
        saldo_inicial = float(request.form.get('saldo_inicial', 0))
        
        # Cria novo movimento de caixa (models.py usará datetime.now() por padrão)
        novo_caixa = MovimentoCaixa(
            saldo_inicial=saldo_inicial,
            usuario_id=current_user.id,
            status='aberto'
        )
        
        db.session.add(novo_caixa)
        db.session.commit()
        
        flash('Caixa aberto com sucesso!', 'success')
        return redirect(url_for('vendas'))
    
    return render_template('abrir_caixa.html')


# =============================================================================
#           INÍCIO DA ROTA MODIFICADA (FECHAR CAIXA)
# =============================================================================
@app.route('/caixa/fechar', methods=['GET', 'POST'])
@login_required
def fechar_caixa():
    """
    Rota para fechamento de caixa
    """
    # Busca caixa aberto
    caixa_aberto, movimento_atual = get_caixa_aberto()
    
    if not caixa_aberto:
        flash('Não há caixa aberto para fechar!', 'warning')
        if current_user.is_admin():
            return redirect(url_for('dashboard'))
        else:
            return redirect(url_for('vendas'))
    
    # --- LÓGICA DO MÉTODO POST (Onde o fechamento ocorre) ---
    if request.method == 'POST':
        saldo_final = float(request.form.get('saldo_final', 0))
        
        # ===========================================================
        #           CORREÇÃO DE FUSO (Usar HORA LOCAL)
        # ===========================================================
        # 1. Define o momento exato do fechamento UMA VEZ (em HORA LOCAL)
        momento_fechamento = datetime.now() # CORRIGIDO (era utcnow)
        
        # 2. Calcula total de vendas do período ATÉ O MOMENTO DO FECHAMENTO (LOCAL)
        vendas_periodo_post = Venda.query.filter(
            Venda.data_venda >= movimento_atual.data_abertura, 
            Venda.data_venda <= momento_fechamento, # <-- Correto
            Venda.usuario_id == current_user.id,
            Venda.status == 'finalizada'
        ).all()
        # ===========================================================
        #           FIM DA CORREÇÃO DE FUSO
        # ===========================================================
        
        # (O total de vendas para o flash message pode ser o geral)
        total_vendas_geral = sum(venda.valor_total for venda in vendas_periodo_post)
        
        # Atualiza movimento de caixa
        movimento_atual.data_fechamento = momento_fechamento
        movimento_atual.saldo_final = saldo_final
        movimento_atual.status = 'fechado'
        
        db.session.commit()
        
        flash(f'Caixa fechado com sucesso! Total de vendas: R$ {total_vendas_geral:.2f}', 'success')
        if current_user.is_admin():
            return redirect(url_for('dashboard'))
        else:
            return redirect(url_for('vendas'))
    
    # --- LÓGICA DO MÉTODO GET (Apenas para exibir a tela) ---
    # Calcula estatísticas para exibir no fechamento
    
    # Query base das vendas no período (abertura local até agora local)
    query_vendas = Venda.query.filter(
        Venda.data_venda >= movimento_atual.data_abertura,
        Venda.data_venda <= datetime.now(), # Filtra até o momento atual
        Venda.usuario_id == current_user.id,
        Venda.status == 'finalizada'
    )
    
    # 1. Total de Vendas (para o JavaScript e contagem)
    vendas_periodo_get = query_vendas.all()
    total_vendas_count = len(vendas_periodo_get)

    # 2. Agrupa os totais pelas novas colunas
    vendas_agrupadas = db.session.query(
        func.sum(Venda.valor_dinheiro - Venda.troco).label('dinheiro'),
        func.sum(Venda.valor_cartao).label('cartao'),
        func.sum(Venda.valor_pix).label('pix')
    ).filter(
        Venda.data_venda >= movimento_atual.data_abertura,
        Venda.data_venda <= datetime.now(), # Filtra até o momento atual
        Venda.usuario_id == current_user.id,
        Venda.status == 'finalizada'
    ).first()

    # Prepara o dicionário de totais
    totais = {
        'dinheiro': float(vendas_agrupadas.dinheiro or 0.0),
        'cartao': float(vendas_agrupadas.cartao or 0.0),
        'pix': float(vendas_agrupadas.pix or 0.0),
        'total_geral': 0.0
    }
    totais['total_geral'] = totais['dinheiro'] + totais['cartao'] + totais['pix']

    # O 'saldo_esperado' é o (Saldo Inicial + Vendas em Dinheiro)
    # O 'total_vendas' (para o script JS) deve ser apenas o de dinheiro
    saldo_esperado_dinheiro = movimento_atual.saldo_inicial + totais['dinheiro']
    
    return render_template('fechar_caixa.html',
                         caixa_aberto=movimento_atual,
                         totais=totais, # Enviando o dict de totais
                         saldo_esperado_dinheiro=saldo_esperado_dinheiro,
                         total_vendas_dinheiro=totais['dinheiro'], # Para o JS
                         total_vendas_count=total_vendas_count)
# =============================================================================
#           FIM DA ROTA MODIFICADA (FECHAR CAIXA)
# =============================================================================


# =============================================================================
# ROTAS DO MENU (ADMIN E PDV)
# =============================================================================

# --- INÍCIO GERENCIAMENTO DE PRODUTOS (CRUD) ---

@app.route('/produtos')
@login_required
def produtos():
    """Rota para gerenciamento de produtos (apenas admin)"""
    if not current_user.is_admin():
        flash('Acesso não autorizado!', 'danger')
        return redirect(url_for('vendas'))
    
    # AGORA BUSCA OS PRODUTOS PARA LISTAR
    produtos_lista = Produto.query.order_by(Produto.id).all()
    # Renderiza o novo template 'produtos.html' (que será uma lista)
    return render_template('produtos.html', produtos=produtos_lista)


@app.route('/produtos/novo', methods=['GET', 'POST'])
@login_required
def produtos_novo():
    """Rota para criar novo produto"""
    if not current_user.is_admin():
        flash('Acesso não autorizado!', 'danger')
        return redirect(url_for('vendas'))

    if request.method == 'POST':
        codigo_barras = request.form.get('codigo_barras')
        nome = request.form.get('nome')
        
        # Verifica se o código de barras já existe
        if Produto.query.filter_by(codigo_barras=codigo_barras).first():
            flash('Este código de barras já está cadastrado.', 'danger')
            # Retorna o formulário com os dados preenchidos
            return render_template('produto_form.html', produto=request.form)

        novo_produto = Produto(
            codigo_barras=codigo_barras,
            nome=nome,
            descricao=request.form.get('descricao'),
            preco_venda=float(request.form.get('preco_venda', 0)),
            preco_custo=float(request.form.get('preco_custo', 0)),
            categoria=request.form.get('categoria'),
            estoque_atual=int(request.form.get('estoque_atual', 0)),
            estoque_minimo=int(request.form.get('estoque_minimo', 0)),
            ativo=True
            # O model usará datetime.now() para data_criacao
        )
        
        # --- Lógica de Upload da Imagem ---
        if 'imagem' in request.files:
            file = request.files['imagem']
            if file and file.filename != '' and allowed_file(file.filename):
                filename = secure_filename(f"{codigo_barras}_{file.filename}")
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(file_path)
                # Salva o caminho *relativo* no banco
                novo_produto.imagem_url = os.path.join(app.config['UPLOAD_FOLDER_REL'], filename).replace("\\", "/")
        # -----------------------------------
        
        db.session.add(novo_produto)
        db.session.commit()
        
        # Registra entrada inicial se estoque > 0
        if novo_produto.estoque_atual > 0:
            movimento = MovimentoEstoque(
                produto_id=novo_produto.id,
                quantidade=novo_produto.estoque_atual,
                tipo_movimento='entrada',
                usuario_id=current_user.id,
                observacao='Cadastro inicial'
            )
            db.session.add(movimento)
            db.session.commit()
            
        flash('Produto criado com sucesso!', 'success')
        return redirect(url_for('produtos'))

    # Método GET: exibe o formulário vazio
    return render_template('produto_form.html')


@app.route('/produtos/editar/<int:id>', methods=['GET', 'POST'])
@login_required
def produtos_editar(id):
    """Rota para editar um produto existente"""
    if not current_user.is_admin():
        flash('Acesso não autorizado!', 'danger')
        return redirect(url_for('vendas'))

    produto = db.session.get(Produto, id) # Usando a nova sintaxe
    if not produto:
        flash('Produto não encontrado.', 'danger')
        return redirect(url_for('produtos'))

    if request.method == 'POST':
        # Pega os dados do formulário
        codigo_barras_novo = request.form.get('codigo_barras')
        
        # Salva estoque antigo antes de modificar
        estoque_antigo = produto.estoque_atual
        
        # Verifica se o código de barras foi alterado e se o novo já existe
        if codigo_barras_novo != produto.codigo_barras and Produto.query.filter_by(codigo_barras=codigo_barras_novo).first():
             flash('Este código de barras já pertence a outro produto.', 'danger')
             return render_template('produto_form.html', produto=produto)

        produto.codigo_barras = codigo_barras_novo
        produto.nome = request.form.get('nome')
        produto.descricao = request.form.get('descricao')
        produto.preco_venda = float(request.form.get('preco_venda', 0))
        produto.preco_custo = float(request.form.get('preco_custo', 0))
        produto.categoria = request.form.get('categoria')
        produto.estoque_atual = int(request.form.get('estoque_atual', 0))
        produto.estoque_minimo = int(request.form.get('estoque_minimo', 0))
        # O model usará datetime.now() para data_atualizacao (onupdate)

        # --- Lógica de Upload da Imagem ---
        if 'imagem' in request.files:
            file = request.files['imagem']
            if file and file.filename != '' and allowed_file(file.filename):
                # (Opcional: deletar a imagem antiga)
                
                filename = secure_filename(f"{produto.codigo_barras}_{file.filename}")
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(file_path)
                produto.imagem_url = os.path.join(app.config['UPLOAD_FOLDER_REL'], filename).replace("\\", "/")
        # -----------------------------------

        db.session.commit()
        
        # Verifica se houve alteração no estoque
        novo_estoque = int(request.form.get('estoque_atual', 0))
        if novo_estoque != estoque_antigo:
            diferenca = novo_estoque - estoque_antigo
            tipo = 'entrada' if diferenca > 0 else 'saida'
            movimento = MovimentoEstoque(
                produto_id=produto.id,
                quantidade=abs(diferenca),
                tipo_movimento=tipo,
                usuario_id=current_user.id,
                observacao='Ajuste manual de estoque'
            )
            db.session.add(movimento)
            db.session.commit()

        flash('Produto atualizado com sucesso!', 'success')
        return redirect(url_for('produtos'))

    # Método GET: exibe o formulário preenchido com dados do produto
    return render_template('produto_form.html', produto=produto)


@app.route('/produtos/deletar/<int:id>', methods=['POST'])
@login_required
def produtos_deletar(id):
    """Rota para deletar (desativar) um produto"""
    if not current_user.is_admin():
        flash('Acesso não autorizado!', 'danger')
        return redirect(url_for('vendas'))

    produto = db.session.get(Produto, id) # Usando a nova sintaxe
    if not produto:
        flash('Produto não encontrado.', 'danger')
        return redirect(url_for('produtos'))

    try:
        # Em vez de deletar, desativamos
        produto.ativo = False
        db.session.commit()
        flash(f'Produto "{produto.nome}" foi desativado.', 'success')

    except Exception as e:
        db.session.rollback()
        flash(f'Não foi possível remover o produto. Erro: {str(e)}', 'danger')

    return redirect(url_for('produtos'))

# =============================================================================
#           INÍCIO DA NOVA ROTA (IMPORTAR EXCEL)
# =============================================================================
@app.route('/produtos/importar', methods=['GET', 'POST'])
@login_required
def produtos_importar():
    """Rota para importar produtos de um arquivo .xlsx"""
    if not current_user.is_admin():
        flash('Acesso não autorizado!', 'danger')
        return redirect(url_for('vendas'))

    if request.method == 'POST':
        # Verifica se o arquivo foi enviado
        if 'arquivo_excel' not in request.files:
            flash('Nenhum arquivo selecionado.', 'danger')
            return redirect(request.url)
        
        file = request.files['arquivo_excel']
        
        # Verifica se o nome do arquivo é válido
        if file.filename == '':
            flash('Nenhum arquivo selecionado.', 'danger')
            return redirect(request.url)

        # Verifica a extensão
        if file and file.filename.endswith('.xlsx'):
            try:
                df = pd.read_excel(file)

                # Verifica as colunas obrigatórias
                colunas_necessarias = ['codigo_barras', 'nome', 'preco_venda', 'preco_custo']
                if not all(col in df.columns for col in colunas_necessarias):
                    flash(f'Arquivo faltando colunas obrigatórias. Verifique o cabeçalho.', 'danger')
                    return redirect(url_for('produtos_importar'))

                sucessos = 0
                erros_existentes = 0
                pulados_vazios = 0
                
                # Itera sobre o DataFrame
                for index, row in df.iterrows():
                    cod_barras = str(row['codigo_barras'])
                    
                    # Pula linha se o código de barras for vazio ou NaN
                    if not cod_barras or pd.isna(cod_barras) or cod_barras.lower() == 'nan':
                        pulados_vazios += 1
                        continue

                    # Verifica se o produto já existe
                    produto_existente = Produto.query.filter_by(codigo_barras=cod_barras).first()
                    if produto_existente:
                        erros_existentes += 1
                        continue # Pula se o código de barras já existe

                    # Cria o novo produto
                    novo_produto = Produto(
                        codigo_barras=cod_barras,
                        nome=str(row['nome']),
                        preco_venda=float(row['preco_venda']),
                        preco_custo=float(row['preco_custo']),
                        # Colunas opcionais (com valores padrão se não existirem)
                        estoque_atual=int(row.get('estoque_atual', 0) or 0),
                        estoque_minimo=int(row.get('estoque_minimo', 0) or 0),
                        descricao=str(row.get('descricao', '')) if pd.notna(row.get('descricao')) else '',
                        categoria=str(row.get('categoria', '')) if pd.notna(row.get('categoria')) else '',
                        ativo=True
                    )
                    db.session.add(novo_produto)
                    db.session.flush() # Necessário para gerar o ID antes do commit
                    if novo_produto.estoque_atual > 0:
                        mov = MovimentoEstoque(
                            produto_id=novo_produto.id,
                            quantidade=novo_produto.estoque_atual,
                            tipo_movimento='entrada',
                            usuario_id=current_user.id,
                            observacao='Importação por lote'
                        )
                        db.session.add(mov)

                    sucessos += 1
                
                # Se o loop terminar sem erros, commita tudo
                db.session.commit()
                flash(f'Importação concluída: {sucessos} produtos cadastrados, {erros_existentes} já existiam, {pulados_vazios} linhas puladas (cód. barras vazio).', 'success')
                return redirect(url_for('produtos'))

            except Exception as e:
                db.session.rollback()
                flash(f'Erro ao processar o arquivo: {e}. Verifique se as colunas e os tipos de dados (ex: números) estão corretos.', 'danger')
                return redirect(url_for('produtos_importar'))

        else:
            flash('Formato de arquivo inválido. Por favor, envie um arquivo .xlsx', 'danger')
            return redirect(request.url)

    # Método GET
    return render_template('produto_importar.html')
# =============================================================================
#           FIM DA NOVA ROTA
# =============================================================================

# --- FIM GERENCIAMENTO DE PRODUTOS ---


# --- INÍCIO GERENCIAMENTO DE USUÁRIOS (CRUD) ---

@app.route('/usuarios')
@login_required
def usuarios():
    """Rota para gerenciamento de usuários (apenas admin)"""
    if not current_user.is_admin():
        flash('Acesso não autorizado!', 'danger')
        return redirect(url_for('vendas'))
    
    usuarios_lista = Usuario.query.order_by(Usuario.nome).all()
    return render_template('usuarios.htm', usuarios=usuarios_lista)

@app.route('/usuarios/novo', methods=['GET', 'POST'])
@login_required
def usuarios_novo():
    """Rota para criar novo usuário"""
    if not current_user.is_admin():
        flash('Acesso não autorizado!', 'danger')
        return redirect(url_for('vendas'))

    if request.method == 'POST':
        nome = request.form.get('nome')
        email = request.form.get('email')
        senha = request.form.get('senha')
        perfil = request.form.get('perfil')

        # Verifica se o email já existe
        if Usuario.query.filter_by(email=email).first():
            flash('Este email já está cadastrado.', 'danger')
            return render_template('usuario_form.htm', 
                                 nome=nome, email=email, perfil=perfil)
        
        # Validação de senha
        if not senha:
             flash('A senha é obrigatória para novos usuários.', 'danger')
             return render_template('usuario_form.htm', 
                                  nome=nome, email=email, perfil=perfil)

        novo_usuario = Usuario(
            nome=nome,
            email=email,
            perfil=perfil,
            ativo=True
            # O model usará datetime.now() para data_criacao
        )
        novo_usuario.set_senha(senha)
        
        db.session.add(novo_usuario)
        db.session.commit()
        
        flash('Usuário criado com sucesso!', 'success')
        return redirect(url_for('usuarios'))

    # Método GET: exibe o formulário vazio
    return render_template('usuario_form.htm')


@app.route('/usuarios/editar/<int:id>', methods=['GET', 'POST'])
@login_required
def usuarios_editar(id):
    """Rota para editar um usuário existente"""
    if not current_user.is_admin():
        flash('Acesso não autorizado!', 'danger')
        return redirect(url_for('vendas'))

    usuario = db.session.get(Usuario, id) # Usando a nova sintaxe
    if not usuario:
        flash('Usuário não encontrado.', 'danger')
        return redirect(url_for('usuarios'))

    if request.method == 'POST':
        # Pega os dados do formulário
        usuario.nome = request.form.get('nome')
        email_novo = request.form.get('email')
        usuario.perfil = request.form.get('perfil')
        senha = request.form.get('senha')
        
        # Verifica se o email foi alterado e se o novo email já existe
        if email_novo != usuario.email and Usuario.query.filter_by(email=email_novo).first():
             flash('Este email já pertence a outro usuário.', 'danger')
             return render_template('usuario_form.htm', usuario=usuario)

        usuario.email = email_novo

        # Atualiza a senha APENAS se o campo não estiver vazio
        if senha:
            usuario.set_senha(senha)
            flash('Usuário e senha atualizados com sucesso!', 'success')
        else:
            flash('Usuário atualizado com sucesso (senha mantida)!', 'success')

        db.session.commit()
        return redirect(url_for('usuarios'))

    # Método GET: exibe o formulário preenchido com dados do usuário
    return render_template('usuario_form.htm', usuario=usuario)


@app.route('/usuarios/deletar/<int:id>', methods=['POST'])
@login_required
def usuarios_deletar(id):
    """Rota para deletar (desativar) um usuário"""
    if not current_user.is_admin():
        flash('Acesso não autorizado!', 'danger')
        return redirect(url_for('vendas'))

    usuario = db.session.get(Usuario, id) # Usando a nova sintaxe
    if not usuario:
        flash('Usuário não encontrado.', 'danger')
        return redirect(url_for('usuarios'))

    # Impede o admin de se auto-deletar
    if usuario.id == current_user.id:
        flash('Você não pode deletar sua própria conta de administrador!', 'danger')
        return redirect(url_for('usuarios'))

    try:
        # Em vez de deletar, é uma boa prática desativar
        usuario.ativo = False
        db.session.commit()
        flash(f'Usuário "{usuario.nome}" foi desativado.', 'success')

    except Exception as e:
        db.session.rollback()
        flash(f'Não foi possível remover o usuário. Erro: {str(e)}', 'danger')

    return redirect(url_for('usuarios'))

# --- FIM GERENCIAMENTO DE USUÁRIOS ---


@app.route('/vendas')
@login_required
def vendas():
    """Rota para PDV de vendas"""
    caixa_aberto, movimento_atual = get_caixa_aberto()
    
    if not caixa_aberto:
        flash('É necessário abrir o caixa primeiro!', 'warning')
        return redirect(url_for('abrir_caixa'))
    
    # O template 'vendas.html' agora cuida da busca de produtos via API
    return render_template('vendas.html')

# =============================================================================
# ROTA DE RELATÓRIOS (ATUALIZADA)
# =============================================================================
@app.route('/relatorios')
@login_required
def relatorios():
    """Rota para relatórios (Apenas Admin)"""
    if not current_user.is_admin():
        flash('Acesso não autorizado!', 'danger')
        return redirect(url_for('vendas'))

    # --- Lógica de Filtro de Data ---
    data_inicio_str = request.args.get('inicio')
    data_fim_str = request.args.get('fim')
    
    # --- Lógica de Filtro de Caixa (Usuário) ---
    caixa_id_str = request.args.get('caixa_id', '0') # '0' significa "Todos"
    caixa_selecionado = 0
    try:
        caixa_selecionado = int(caixa_id_str)
    except ValueError:
        caixa_selecionado = 0 # Volta para "Todos" se o valor for inválido

    # --- Lógica de Filtro de Forma de Pagamento ---
    forma_pgto_selecionada = request.args.get('forma_pgto', 'todos') # 'todos' é o padrão

    # ===================================================================
    #           INÍCIO DA CORREÇÃO (PADRÃO DE 7 DIAS EM HORA LOCAL)
    # ===================================================================
    # Define o padrão (últimos 7 dias) se nenhuma data for fornecida
    hoje_local = date.today() # CORRIGIDO
    if not data_inicio_str:
        # Pega 6 dias atrás (para completar 7 dias)
        data_inicio_str = (hoje_local - timedelta(days=6)).strftime('%Y-%m-%d')
    if not data_fim_str:
        data_fim_str = hoje_local.strftime('%Y-%m-%d')
    # ===================================================================
    #            FIM DA CORREÇÃO (PADRÃO DE 7 DIAS EM HORA LOCAL)
    # ===================================================================

    try:
        # Converte as strings para objetos datetime (início do dia e fim do dia)
        data_inicio = datetime.strptime(data_inicio_str, '%Y-%m-%d').replace(hour=0, minute=0, second=0)
        data_fim = datetime.strptime(data_fim_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
    except ValueError:
        flash('Formato de data inválido.', 'danger')
        # Se inválido, volta para o padrão de 7 dias LOCAL
        data_fim_dt_local = datetime.now().replace(hour=23, minute=59, second=59) # CORRIGIDO
        data_inicio_dt_local = (data_fim_dt_local - timedelta(days=6)).replace(hour=0, minute=0, second=0) # CORRIGIDO
        data_inicio_str = data_inicio_dt_local.strftime('%Y-%m-%d')
        data_fim_str = data_fim_dt_local.strftime('%Y-%m-%d')
        # Define os objetos de data/hora para a consulta
        data_inicio = data_inicio_dt_local
        data_fim = data_fim_dt_local


    # Busca todos os caixas (usuários) para o filtro dropdown
    caixas = Usuario.query.order_by(Usuario.nome).all()
    nome_filtro = "Geral (Todos os Caixas)"

    # --- 1. Consultas para o Sumário ---
    # Define o campo a ser somado baseado no filtro de pagamento
    if forma_pgto_selecionada == 'dinheiro':
        campo_soma = db.func.sum(Venda.valor_dinheiro - Venda.troco)
    elif forma_pgto_selecionada == 'cartao':
        campo_soma = db.func.sum(Venda.valor_cartao)
    elif forma_pgto_selecionada == 'pix':
        campo_soma = db.func.sum(Venda.valor_pix)
    else:
        campo_soma = db.func.sum(Venda.valor_total)

    query_sumario = db.session.query(
        db.func.count(Venda.id).label('num_vendas'),
        campo_soma.label('total_vendido')
    ).filter(
        Venda.status == 'finalizada',
        Venda.data_venda.between(data_inicio, data_fim)
    )
    
    # Aplica filtro de caixa se um específico foi selecionado
    if caixa_selecionado > 0:
        query_sumario = query_sumario.filter(Venda.usuario_id == caixa_selecionado)
        usuario_filtro = db.session.get(Usuario, caixa_selecionado)
        if usuario_filtro:
            nome_filtro = f"Caixa: {usuario_filtro.nome}"

    # Aplica filtro de forma de pagamento
    if forma_pgto_selecionada == 'dinheiro':
        query_sumario = query_sumario.filter(Venda.valor_dinheiro > 0)
    elif forma_pgto_selecionada == 'cartao':
        query_sumario = query_sumario.filter(Venda.valor_cartao > 0)
    elif forma_pgto_selecionada == 'pix':
        query_sumario = query_sumario.filter(Venda.valor_pix > 0)
    elif forma_pgto_selecionada == 'multiplo':
        query_sumario = query_sumario.filter(Venda.forma_pagamento == 'multiplo')

    sumario = query_sumario.first()

    # Cálculo do Ticket Médio
    total_vendido = sumario.total_vendido or 0
    num_vendas = sumario.num_vendas or 0
    ticket_medio = (total_vendido / num_vendas) if num_vendas > 0 else 0

    # --- 1.5. Consulta de Totais por Forma de Pagamento ---
    query_totais_pgto = db.session.query(
        db.func.sum(Venda.valor_dinheiro - Venda.troco).label('dinheiro'),
        db.func.sum(Venda.valor_cartao).label('cartao'),
        db.func.sum(Venda.valor_pix).label('pix')
    ).filter(
        Venda.status == 'finalizada',
        Venda.data_venda.between(data_inicio, data_fim)
    )
    if caixa_selecionado > 0:
        query_totais_pgto = query_totais_pgto.filter(Venda.usuario_id == caixa_selecionado)
    
    totais_pgto = query_totais_pgto.first()
    total_dinheiro = totais_pgto.dinheiro or 0
    total_cartao = totais_pgto.cartao or 0
    total_pix = totais_pgto.pix or 0

    # --- 2. Consulta de Produtos Mais Vendidos ---
    query_produtos = db.session.query(
        Produto.nome,
        Produto.codigo_barras,
        db.func.sum(ItemVenda.quantidade).label('total_quantidade'),
        db.func.sum(ItemVenda.subtotal).label('total_arrecadado')
    ).join(ItemVenda, ItemVenda.produto_id == Produto.id)\
     .join(Venda, Venda.id == ItemVenda.venda_id)\
     .filter(
        Venda.status == 'finalizada',
        Venda.data_venda.between(data_inicio, data_fim)
     )
    
    # Aplica filtro de caixa
    if caixa_selecionado > 0:
        query_produtos = query_produtos.filter(Venda.usuario_id == caixa_selecionado)

    # Aplica filtro de forma de pagamento
    if forma_pgto_selecionada == 'dinheiro':
        query_produtos = query_produtos.filter(Venda.valor_dinheiro > 0)
    elif forma_pgto_selecionada == 'cartao':
        query_produtos = query_produtos.filter(Venda.valor_cartao > 0)
    elif forma_pgto_selecionada == 'pix':
        query_produtos = query_produtos.filter(Venda.valor_pix > 0)
    elif forma_pgto_selecionada == 'multiplo':
        query_produtos = query_produtos.filter(Venda.forma_pagamento == 'multiplo')

    produtos_vendidos = query_produtos.group_by(Produto.id)\
                                      .order_by(db.func.sum(ItemVenda.quantidade).desc())\
                                      .limit(10)\
                                      .all()

    # --- 3. Consulta de Vendas (Detalhe Geral - Cupons) ---
    query_vendas = db.session.query(Venda).filter(
        Venda.status == 'finalizada',
        Venda.data_venda.between(data_inicio, data_fim)
    )
    
    # Aplica filtro de caixa
    if caixa_selecionado > 0:
        query_vendas = query_vendas.filter(Venda.usuario_id == caixa_selecionado)
        
    # Aplica filtro de forma de pagamento
    if forma_pgto_selecionada == 'dinheiro':
        query_vendas = query_vendas.filter(Venda.valor_dinheiro > 0)
    elif forma_pgto_selecionada == 'cartao':
        query_vendas = query_vendas.filter(Venda.valor_cartao > 0)
    elif forma_pgto_selecionada == 'pix':
        query_vendas = query_vendas.filter(Venda.valor_pix > 0)
    elif forma_pgto_selecionada == 'multiplo':
        query_vendas = query_vendas.filter(Venda.forma_pagamento == 'multiplo')

    vendas_detalhe = query_vendas.order_by(Venda.data_venda.desc()).all()


    return render_template('relatorios.html',
                         data_inicio=data_inicio_str,
                         data_fim=data_fim_str,
                         total_vendido=total_vendido,
                         num_vendas=num_vendas,
                         ticket_medio=ticket_medio,
                         total_dinheiro=total_dinheiro,
                         total_cartao=total_cartao,
                         total_pix=total_pix,
                         produtos_vendidos=produtos_vendidos,
                         vendas_detalhe=vendas_detalhe,
                         caixas=caixas, # Envia a lista de caixas para o filtro
                         caixa_selecionado=caixa_selecionado, # Envia o ID do caixa selecionado
                         nome_filtro=nome_filtro, # Envia o nome do filtro
                         forma_pgto_selecionada=forma_pgto_selecionada # Envia a forma de pgto
                         )


# =============================================================================
# NOVAS ROTAS DE AÇÃO EM RELATÓRIOS (CANCELAMENTO E ALTERAÇÃO DE PAGAMENTO)
# =============================================================================

@app.route('/venda/cancelar/<int:id>', methods=['POST'])
@login_required
def cancelar_venda(id):
    """Rota para cancelar uma venda e restaurar o estoque"""
    if not current_user.is_admin():
        flash('Acesso não autorizado!', 'danger')
        return redirect(url_for('relatorios', **request.args.to_dict()))
    
    venda = db.session.get(Venda, id)
    if not venda:
        flash('Venda não encontrada.', 'danger')
        return redirect(url_for('relatorios', **request.args.to_dict()))
        
    if venda.status == 'cancelada':
        flash('Venda já está cancelada.', 'warning')
        return redirect(url_for('relatorios', **request.args.to_dict()))
        
    try:
        # Restaurar estoque
        for item in venda.itens:
            produto = db.session.get(Produto, item.produto_id)
            if produto:
                produto.estoque_atual += item.quantidade
                
                # Registra devolução
                movimento = MovimentoEstoque(
                    produto_id=produto.id,
                    quantidade=item.quantidade,
                    tipo_movimento='devolucao',
                    usuario_id=current_user.id,
                    referencia_id=venda.id,
                    observacao=f'Cancelamento da Venda {venda.numero_venda}'
                )
                db.session.add(movimento)
                
        # Atualizar status da venda
        venda.status = 'cancelada'
        db.session.commit()
        flash(f'Venda {venda.numero_venda} cancelada com sucesso. Estoque restaurado.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao cancelar venda: {str(e)}', 'danger')
        
    return redirect(url_for('relatorios', **request.args.to_dict()))


@app.route('/venda/alterar_pagamento/<int:id>', methods=['POST'])
@login_required
def alterar_pagamento(id):
    """Rota para alterar a forma de pagamento de uma venda (apenas dinheiro, cartão e pix)"""
    if not current_user.is_admin():
        flash('Acesso não autorizado!', 'danger')
        return redirect(url_for('relatorios', **request.args.to_dict()))
        
    nova_forma = request.form.get('nova_forma_pagamento')
    if nova_forma not in ['dinheiro', 'cartao', 'pix']:
        flash('Forma de pagamento inválida para alteração.', 'danger')
        return redirect(url_for('relatorios', **request.args.to_dict()))
        
    venda = db.session.get(Venda, id)
    if not venda:
        flash('Venda não encontrada.', 'danger')
        return redirect(url_for('relatorios', **request.args.to_dict()))
        
    if venda.status == 'cancelada':
        flash('Não é possível alterar a forma de pagamento de uma venda cancelada.', 'danger')
        return redirect(url_for('relatorios', **request.args.to_dict()))
        
    if venda.forma_pagamento not in ['dinheiro', 'cartao', 'pix']:
        flash('Apenas vendas simples em dinheiro, cartão ou pix podem ter a forma de pagamento alterada.', 'warning')
        return redirect(url_for('relatorios', **request.args.to_dict()))
        
    try:
        venda.forma_pagamento = nova_forma
        
        # Zera todos os valores específicos de pagamento
        venda.valor_dinheiro = 0.0
        venda.valor_cartao = 0.0
        venda.valor_pix = 0.0
        venda.troco = 0.0
        
        venda.valor_pago = venda.valor_total
        
        if nova_forma == 'dinheiro':
            venda.valor_dinheiro = venda.valor_total
        elif nova_forma == 'cartao':
            venda.valor_cartao = venda.valor_total
        elif nova_forma == 'pix':
            venda.valor_pix = venda.valor_total

        db.session.commit()
        flash(f'Forma de pagamento da venda {venda.numero_venda} alterada para {nova_forma.title()} com sucesso.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao alterar pagamento: {str(e)}', 'danger')
        
    return redirect(url_for('relatorios', **request.args.to_dict()))
# --- NOVA ROTA PARA O CUPOM ---
@app.route('/venda/cupom/<int:venda_id>')
@login_required
def cupom_venda(venda_id):
    """
    Exibe o cupom (recibo) de uma venda finalizada para impressão.
    """
    venda = db.session.get(Venda, venda_id) # Usando a nova sintaxe
    if not venda:
        flash('Venda não encontrada.', 'danger')
        return redirect(url_for('dashboard'))
    
    # Verificação de segurança: Apenas o admin ou o operador que fez a venda podem vê-la
    if not current_user.is_admin() and venda.usuario_id != current_user.id:
        flash('Acesso não autorizado a este cupom.', 'danger')
        return redirect(url_for('vendas'))
            
    # Renderiza um novo template 'cupom.html'
    return render_template('cupom.html', venda=venda)


@app.route('/venda/cupom_orcamento/<int:orcamento_id>')
@login_required
def cupom_orcamento(orcamento_id):
    """
    Exibe o cupom de orçamento para impressão.
    """
    orcamento = db.session.get(Venda, orcamento_id)
    if not orcamento:
        flash('Orçamento não encontrado.', 'danger')
        return redirect(url_for('dashboard'))
    
    if orcamento.status != 'orcamento':
        flash('Este registro não é um orçamento.', 'warning')
        return redirect(url_for('vendas'))
    
    return render_template('orcamento.html', orcamento=orcamento)


# =============================================================================
#           INÍCIO DA NOVA ROTA (EXPORTAR EXCEL)
# =============================================================================
@app.route('/relatorios/exportar')
@login_required
def exportar_relatorio():
    """
    Gera e baixa uma planilha Excel com os dados do relatório de vendas.
    """
    if not current_user.is_admin():
        flash('Acesso não autorizado!', 'danger')
        return redirect(url_for('vendas'))

    # --- 1. REPETE A LÓGICA DE FILTRO DA ROTA 'relatorios' ---
    # (Pega os valores da query string)
    data_inicio_str = request.args.get('inicio')
    data_fim_str = request.args.get('fim')
    caixa_id_str = request.args.get('caixa_id', '0')
    caixa_selecionado = int(caixa_id_str)
    forma_pgto_selecionada = request.args.get('forma_pgto', 'todos')

    # ===========================================================
    #           CORREÇÃO DE FUSO (Usar HORA LOCAL)
    # ===========================================================
    # (Define o padrão de 7 dias LOCAL se não vier na query string)
    hoje_local = date.today() # CORRIGIDO
    if not data_inicio_str:
        data_inicio_str = (hoje_local - timedelta(days=6)).strftime('%Y-%m-%d')
    if not data_fim_str:
        data_fim_str = hoje_local.strftime('%Y-%m-%d')

    try:
        data_inicio = datetime.strptime(data_inicio_str, '%Y-%m-%d').replace(hour=0, minute=0, second=0)
        data_fim = datetime.strptime(data_fim_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
    except ValueError:
        data_fim_dt_local = datetime.now().replace(hour=23, minute=59, second=59) # CORRIGIDO
        data_inicio_dt_local = (data_fim_dt_local - timedelta(days=6)).replace(hour=0, minute=0, second=0) # CORRIGIDO
        data_inicio_str = data_inicio_dt_local.strftime('%Y-%m-%d')
        data_fim_str = data_fim_dt_local.strftime('%Y-%m-%d')
        data_inicio = data_inicio_dt_local
        data_fim = data_fim_dt_local
    # ===========================================================
    #           FIM DA CORREÇÃO DE FUSO
    # ===========================================================


    # --- 2. EXECUTA A MESMA CONSULTA DE VENDAS ---
    query_vendas = db.session.query(Venda).filter(
        Venda.status == 'finalizada',
        Venda.data_venda.between(data_inicio, data_fim)
    )
    
    if caixa_selecionado > 0:
        query_vendas = query_vendas.filter(Venda.usuario_id == caixa_selecionado)
    if forma_pgto_selecionada == 'dinheiro':
        query_vendas = query_vendas.filter(Venda.valor_dinheiro > 0)
    elif forma_pgto_selecionada == 'cartao':
        query_vendas = query_vendas.filter(Venda.valor_cartao > 0)
    elif forma_pgto_selecionada == 'pix':
        query_vendas = query_vendas.filter(Venda.valor_pix > 0)
    elif forma_pgto_selecionada == 'multiplo':
        query_vendas = query_vendas.filter(Venda.forma_pagamento == 'multiplo')

    vendas_detalhe = query_vendas.order_by(Venda.data_venda.desc()).all()

    # --- 3. PREPARA OS DADOS PARA O PANDAS ---
    dados_para_planilha = []
    for venda in vendas_detalhe:
        dados_para_planilha.append({
            'Nº Cupom': venda.numero_venda,
            'Data Venda': venda.data_venda.strftime('%Y-%m-%d %H:%M:%S'),
            'Qtd.': sum(item.quantidade for item in venda.itens),
            'Subtotal (R$)': venda.valor_total,
            'Forma Pgto': venda.forma_pagamento.title(),
            'Operador': venda.operador.nome
        })

    if not dados_para_planilha:
        flash('Nenhum dado encontrado para exportar.', 'warning')
        return redirect(url_for('relatorios', **request.args))

    # --- 4. GERA A PLANILHA EM MEMÓRIA ---
    df = pd.DataFrame(dados_para_planilha)
    
    # Cria um buffer de Bytes em memória
    output = io.BytesIO()
    
    # Escreve o DataFrame no buffer usando ExcelWriter
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='Relatorio_Vendas', index=False)
    
    output.seek(0) # Volta ao início do buffer

    # --- 5. CRIA A RESPOSTA E ENVIA O ARQUIVO ---
    nome_arquivo = f"Relatorio_Vendas_{data_inicio_str}_a_{data_fim_str}.xlsx"
    
    response = make_response(output.read())
    response.headers["Content-Disposition"] = f"attachment; filename={nome_arquivo}"
    response.headers["Content-type"] = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    
    return response

# =============================================================================
#           FIM DA NOVA ROTA (EXPORTAR EXCEL)
# =============================================================================


# =============================================================================
# ROTAS DO PDV (PONTO DE VENDA) - API
# =============================================================================

# --- ROTA DA API MODIFICADA (BUSCA POR CÓDIGO E ID) ---
@app.route('/api/produto/<string:codigo>')
@login_required
def api_buscar_produto(codigo):
    """
    API para buscar produto pelo código de barras OU pelo ID.
    Chamado pelo JavaScript do PDV.
    """
    # Verifica se o caixa está aberto
    caixa_aberto, _ = get_caixa_aberto()
    if not caixa_aberto:
        return jsonify({'error': 'Caixa está fechado!'}), 403
    
    produto = None
    
    # 1. Tenta buscar pelo Código de Barras primeiro
    produto = Produto.query.filter_by(codigo_barras=codigo, ativo=True).first()
    
    # 2. Se não encontrou, tenta buscar pelo ID (Código do Produto)
    if not produto:
        try:
            # Tenta converter o código para um inteiro (ID)
            produto_id = int(codigo)
            produto = db.session.get(Produto, produto_id) # Usando a nova sintaxe
            # Verifica se o produto encontrado por ID está ativo
            if produto and not produto.ativo:
                produto = None # Se não estiver ativo, trata como não encontrado
        except ValueError:
            # Se o código não for um número, ignora a busca por ID
            pass

    # 3. Se não encontrou, tenta buscar pelo Nome (parcial ou exato)
    if not produto:
        produto = Produto.query.filter(
            Produto.nome.ilike(f"%{codigo}%"),
            Produto.ativo == True
        ).first()

    # 4. Verifica o resultado da busca
    if not produto:
        return jsonify({'error': 'Produto não encontrado'}), 404
        
    if produto.estoque_atual <= 0:
        return jsonify({'error': f'Produto sem estoque: {produto.nome}'}), 400
        
    # GERA A URL DA IMAGEM SE ELA EXISTIR
    imagem_path = None
    if produto.imagem_url:
        # Usa url_for para gerar o caminho correto
        imagem_path = url_for('static', filename=produto.imagem_url.replace('static/', '', 1))
        
    return jsonify({
        'id': produto.id,
        'nome': produto.nome,
        'preco_venda': produto.preco_venda,
        'estoque_atual': produto.estoque_atual,
        'imagem_url': imagem_path
    })

# =============================================================================
#           INÍCIO DA NOVA ROTA (BUSCAR POR NOME - F2)
# =============================================================================
@app.route('/api/produtos/buscar')
@login_required
def api_buscar_produtos_por_nome():
    """
    API para buscar produtos por nome ou código de barras (para o modal F2).
    """
    # Verifica se o caixa está aberto
    caixa_aberto, _ = get_caixa_aberto()
    if not caixa_aberto:
        return jsonify({'error': 'Caixa está fechado!'}), 403
        
    termo_busca = request.args.get('nome', '')
    
    if len(termo_busca) < 2:
        return jsonify([]) # Retorna lista vazia se a busca for muito curta

    # Cria o filtro (ilike não diferencia maiúsculas/minúsculas)
    filtro_like = f"%{termo_busca}%"
    
    # Busca por nome, código de barras OU id
    filtros = [
        Produto.nome.ilike(filtro_like),
        Produto.codigo_barras.ilike(filtro_like)
    ]
    if termo_busca.isdigit():
        filtros.append(Produto.id == int(termo_busca))
        
    produtos_encontrados = Produto.query.filter(
        or_(*filtros),
        Produto.ativo == True
    ).order_by(Produto.nome).limit(20).all() # Limita a 20 resultados

    # Formata os resultados
    resultados_json = []
    for produto in produtos_encontrados:
        imagem_path = None
        if produto.imagem_url:
            imagem_path = url_for('static', filename=produto.imagem_url.replace('static/', '', 1))
            
        resultados_json.append({
            'id': produto.id,
            'nome': produto.nome,
            'codigo_barras': produto.codigo_barras,
            'preco_venda': produto.preco_venda,
            'estoque_atual': produto.estoque_atual,
            'imagem_url': imagem_path
        })
        
    return jsonify(resultados_json)
# =============================================================================
#           FIM DA NOVA ROTA
# =============================================================================

# =============================================================================
#           INÍCIO DA NOVA ROTA (LISTAR/CARREGAR ORÇAMENTOS)
# =============================================================================
def limpar_orcamentos_vencidos():
    """Cancela orçamentos mais antigos que 7 dias"""
    limite = datetime.now() - timedelta(days=7)
    vencidos = Venda.query.filter(
        Venda.status == 'orcamento',
        Venda.data_venda < limite
    ).all()
    
    for orc in vencidos:
        orc.status = 'cancelada'
    
    if vencidos:
        db.session.commit()

@app.route('/api/orcamentos_pendentes')
@login_required
def api_orcamentos_pendentes():
    # Verifica se o caixa está aberto
    caixa_aberto, _ = get_caixa_aberto()
    if not caixa_aberto:
        return jsonify({'error': 'Caixa está fechado!'}), 403
        
    limpar_orcamentos_vencidos()
    
    pendentes = Venda.query.filter_by(status='orcamento').order_by(Venda.data_venda.desc()).limit(50).all()
    
    resultados = []
    for p in pendentes:
        resultados.append({
            'id': p.id,
            'numero': p.numero_venda,
            'data': p.data_venda.strftime('%d/%m/%Y %H:%M'),
            'operador': p.operador.nome,
            'total': p.valor_total
        })
        
    return jsonify(resultados)

@app.route('/api/orcamento/<int:id>')
@login_required
def api_carregar_orcamento(id):
    caixa_aberto, _ = get_caixa_aberto()
    if not caixa_aberto:
        return jsonify({'error': 'Caixa está fechado!'}), 403
        
    orcamento = db.session.get(Venda, id)
    if not orcamento or orcamento.status != 'orcamento':
        return jsonify({'error': 'Orçamento não encontrado ou inativo.'}), 404
        
    itens_json = []
    for item in orcamento.itens:
        itens_json.append({
            'id': item.produto.id,
            'nome': item.produto.nome,
            'preco_venda': item.preco_unitario,
            'quantidade': item.quantidade,
            'subtotal': item.subtotal
        })
        
    return jsonify({
        'id': orcamento.id,
        'numero': orcamento.numero_venda,
        'itens': itens_json
    })
# =============================================================================
#           FIM DA NOVA ROTA (LISTAR/CARREGAR ORÇAMENTOS)
# =============================================================================

@app.route('/vendas/finalizar', methods=['POST'])
@login_required
def finalizar_venda():
    """
    API para finalizar a venda.
    Recebe os dados do carrinho via JSON do JavaScript.
    """
    # Verifica se o caixa está aberto
    caixa_aberto, movimento_atual = get_caixa_aberto()
    if not caixa_aberto:
        return jsonify({'error': 'Caixa está fechado!'}), 403

    # Pega os dados enviados pelo JavaScript
    data = request.get_json()
    
    if not data or 'itens' not in data or not data['itens']:
        return jsonify({'error': 'Carrinho vazio'}), 400

    try:
        # Inicia a transação
        
        valor_total_venda = 0
        itens_venda_db = []
        
        # ===========================================================
        #           CORREÇÃO DE FUSO (Usar HORA LOCAL)
        # ===========================================================
        # Gera o número da venda (usando timestamp LOCAL para consistência)
        numero_venda = f"V{int(datetime.now().timestamp())}" # CORRIGIDO (era utcnow)
        # ===========================================================
        
        # --- INÍCIO DA CORREÇÃO (NoneType para float) ---
        # Pega o valor_pago do JSON
        valor_pago_json = data.get('valor_pago')
        # Garante que não seja NoneType antes de converter. Se for None, usa 0.
        valor_pago_float = float(valor_pago_json or 0)

        # Cria a Venda principal (o model usará datetime.now() por padrão)
        nova_venda = Venda(
            numero_venda=numero_venda,
            valor_total=0, # Será calculado
            valor_pago=valor_pago_float, # Usa o valor seguro
            valor_dinheiro=float(data.get('valor_dinheiro', 0) or 0),
            valor_cartao=float(data.get('valor_cartao', 0) or 0),
            valor_pix=float(data.get('valor_pix', 0) or 0),
            forma_pagamento=data.get('forma_pagamento', 'dinheiro'),
            status='finalizada',
            usuario_id=current_user.id
        )
        # --- FIM DA CORREÇÃO ---
        
        # Loop nos itens do carrinho para validar estoque e calcular total
        for item_json in data['itens']:
            produto = db.session.get(Produto, item_json['id']) # Usando a nova sintaxe
            quantidade = int(item_json['quantidade'])
            
            if not produto:
                raise Exception(f'Produto ID {item_json["id"]} não encontrado.')
                
            if produto.estoque_atual < quantidade:
                raise Exception(f'Estoque insuficiente para {produto.nome}. (Disponível: {produto.estoque_atual})')

            # Atualiza estoque
            produto.estoque_atual -= quantidade
            
            # Calcula subtotal
            preco_unitario = produto.preco_venda
            subtotal = preco_unitario * quantidade
            valor_total_venda += subtotal
            
            # Cria o ItemVenda
            novo_item_venda = ItemVenda(
                produto_id=produto.id,
                quantidade=quantidade,
                preco_unitario=preco_unitario,
                subtotal=subtotal
            )
            itens_venda_db.append(novo_item_venda)

        # Atualiza a Venda principal com os valores corretos
        nova_venda.valor_total = valor_total_venda
        
        # Calcula o troco
        if nova_venda.forma_pagamento == 'dinheiro':
            nova_venda.troco = nova_venda.valor_pago - nova_venda.valor_total
            if nova_venda.troco < 0:
                 raise Exception('Valor pago em dinheiro é insuficiente.')
        elif nova_venda.forma_pagamento == 'multiplo':
            nova_venda.troco = nova_venda.valor_pago - nova_venda.valor_total
            if nova_venda.troco < 0:
                 raise Exception('A soma dos múltiplos valores é insuficiente.')
            if nova_venda.troco > nova_venda.valor_dinheiro:
                 raise Exception('O troco não pode ser maior que o valor pago em dinheiro.')
        else:
            nova_venda.valor_pago = valor_total_venda # Garante que valor pago é o total
            nova_venda.troco = 0

        # Adiciona os itens à venda (o backref cuida do venda_id)
        nova_venda.itens = itens_venda_db
        
        # Verifica se veio de um orçamento existente para conversão
        orcamento_origem_id = data.get('orcamento_origem_id')
        if orcamento_origem_id:
            orc_origem = db.session.get(Venda, orcamento_origem_id)
            if orc_origem and orc_origem.status == 'orcamento':
                orc_origem.status = 'aprovado'
        
        # Salva tudo no banco
        db.session.add(nova_venda)
        db.session.commit()
        
        # Registra saída no estoque para cada item
        for item in itens_venda_db:
            movimento = MovimentoEstoque(
                produto_id=item.produto_id,
                quantidade=item.quantidade,
                tipo_movimento='saida',
                usuario_id=current_user.id,
                referencia_id=nova_venda.id,
                observacao=f'Venda {nova_venda.numero_venda}'
            )
            db.session.add(movimento)
        db.session.commit()
        
        return jsonify({
            'success': 'Venda finalizada com sucesso!',
            'venda_id': nova_venda.id,
            'numero_venda': nova_venda.numero_venda
        })

    except Exception as e:
        db.session.rollback() # Desfaz qualquer mudança no banco em caso de erro
        return jsonify({'error': str(e)}), 400

# =============================================================================
#           INÍCIO DA NOVA ROTA (ORÇAMENTO)
# =============================================================================
@app.route('/vendas/orcamento', methods=['POST'])
@login_required
def gerar_orcamento():
    """
    API para gerar um orçamento.
    Recebe os dados do carrinho via JSON do JavaScript.
    Não deduz estoque e não exige pagamento.
    """
    # Verifica se o caixa está aberto (opcional para orçamento, mas vamos manter a consistência)
    caixa_aberto, movimento_atual = get_caixa_aberto()
    if not caixa_aberto:
        return jsonify({'error': 'Caixa está fechado!'}), 403

    data = request.get_json()
    
    if not data or 'itens' not in data or not data['itens']:
        return jsonify({'error': 'Carrinho vazio'}), 400

    try:
        valor_total_orcamento = 0
        itens_orcamento_db = []
        
        # Gera o número do orçamento
        numero_orcamento = f"ORC-{int(datetime.now().timestamp())}"
        
        # Cria a "Venda" como Orçamento
        novo_orcamento = Venda(
            numero_venda=numero_orcamento,
            valor_total=0,
            valor_pago=0,
            valor_dinheiro=0,
            valor_cartao=0,
            valor_pix=0,
            troco=0,
            forma_pagamento='orcamento',
            status='orcamento',
            usuario_id=current_user.id
        )
        
        # Loop nos itens para calcular total (sem deduzir estoque)
        for item_json in data['itens']:
            produto = db.session.get(Produto, item_json['id'])
            quantidade = int(item_json['quantidade'])
            
            if not produto:
                raise Exception(f'Produto ID {item_json["id"]} não encontrado.')
                
            # Apenas avisa se não tem estoque, mas permite o orçamento
            if produto.estoque_atual < quantidade:
                # Opcional: poderíamos retornar um aviso, mas para orçamento tudo bem
                pass

            # Calcula subtotal
            preco_unitario = produto.preco_venda
            subtotal = preco_unitario * quantidade
            valor_total_orcamento += subtotal
            
            # Cria o ItemVenda
            novo_item = ItemVenda(
                produto_id=produto.id,
                quantidade=quantidade,
                preco_unitario=preco_unitario,
                subtotal=subtotal
            )
            itens_orcamento_db.append(novo_item)

        novo_orcamento.valor_total = valor_total_orcamento
        novo_orcamento.itens = itens_orcamento_db
        
        db.session.add(novo_orcamento)
        db.session.commit()
        
        return jsonify({
            'success': 'Orçamento gerado com sucesso!',
            'orcamento_id': novo_orcamento.id,
            'numero_orcamento': novo_orcamento.numero_venda
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400
# =============================================================================
#           FIM DA NOVA ROTA (ORÇAMENTO)
# =============================================================================

# =============================================================================
#           INÍCIO DA NOVA ROTA (CUPOM FECHAMENTO)
# =============================================================================

@app.route('/caixa/cupom_fechamento')
@app.route('/caixa/cupom_fechamento/<int:movimento_id>')
@login_required
def cupom_fechamento(movimento_id=None):
    """
    Gera um cupom/relatório de fechamento para o caixa ativo ou histórico.
    """
    if movimento_id is not None:
        movimento_atual = db.session.get(MovimentoCaixa, movimento_id)
        if not movimento_atual:
            flash('Movimento de caixa não encontrado.', 'danger')
            return redirect(url_for('dashboard'))
        # Verifica permissão: apenas Admin ou o próprio operador do caixa
        if not current_user.is_admin() and movimento_atual.usuario_id != current_user.id:
            flash('Acesso não autorizado!', 'danger')
            return redirect(url_for('vendas'))
    else:
        caixa_aberto, movimento_atual = get_caixa_aberto()
        if not caixa_aberto:
            flash('Não há caixa aberto para gerar relatório.', 'warning')
            if current_user.is_admin():
                return redirect(url_for('dashboard'))
            return redirect(url_for('vendas'))

    # Para buscar as vendas do período
    data_limite = movimento_atual.data_fechamento if movimento_atual.status == 'fechado' else datetime.now()
    
    query_vendas = Venda.query.filter(
        Venda.data_venda >= movimento_atual.data_abertura,
        Venda.data_venda <= data_limite,
        Venda.usuario_id == movimento_atual.usuario_id,
        Venda.status == 'finalizada'
    )
    
    vendas_periodo = query_vendas.all()
    total_vendas_count = len(vendas_periodo)

    vendas_agrupadas = db.session.query(
        func.sum(Venda.valor_dinheiro - Venda.troco).label('dinheiro'),
        func.sum(Venda.valor_cartao).label('cartao'),
        func.sum(Venda.valor_pix).label('pix')
    ).filter(
        Venda.data_venda >= movimento_atual.data_abertura,
        Venda.data_venda <= data_limite,
        Venda.usuario_id == movimento_atual.usuario_id,
        Venda.status == 'finalizada'
    ).first()

    totais = {
        'dinheiro': float(vendas_agrupadas.dinheiro or 0.0),
        'cartao': float(vendas_agrupadas.cartao or 0.0),
        'pix': float(vendas_agrupadas.pix or 0.0),
        'total_geral': 0.0,
        'total_vendas_count': total_vendas_count
    }
    totais['total_geral'] = totais['dinheiro'] + totais['cartao'] + totais['pix']
    
    saldo_esperado_dinheiro = movimento_atual.saldo_inicial + totais['dinheiro']

    return render_template('cupom_fechamento.html', 
                         caixa=movimento_atual,
                         totais=totais,
                         saldo_esperado_dinheiro=saldo_esperado_dinheiro)

# =============================================================================
#           FIM DA NOVA ROTA (CUPOM FECHAMENTO)
# =============================================================================

# =============================================================================
# RELATÓRIO DE FECHAMENTO DE CAIXA (NOVO)
# =============================================================================
@app.route('/relatorios/fechamento_caixa')
@login_required
def relatorio_fechamento_caixa():
    """Rota para relatórios de fechamento de caixa dos operadores (Apenas Admin)"""
    if not current_user.is_admin():
        flash('Acesso não autorizado!', 'danger')
        return redirect(url_for('vendas'))

    data_inicio_str = request.args.get('inicio')
    data_fim_str = request.args.get('fim')
    
    caixa_id_str = request.args.get('caixa_id', '0')
    caixa_selecionado = 0
    try:
        caixa_selecionado = int(caixa_id_str)
    except ValueError:
        caixa_selecionado = 0

    status_selecionado = request.args.get('status', 'todos')

    hoje_local = date.today()
    if not data_inicio_str:
        data_inicio_str = (hoje_local - timedelta(days=6)).strftime('%Y-%m-%d')
    if not data_fim_str:
        data_fim_str = hoje_local.strftime('%Y-%m-%d')

    try:
        data_inicio = datetime.strptime(data_inicio_str, '%Y-%m-%d').replace(hour=0, minute=0, second=0)
        data_fim = datetime.strptime(data_fim_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
    except ValueError:
        flash('Formato de data inválido.', 'danger')
        data_fim = datetime.now().replace(hour=23, minute=59, second=59)
        data_inicio = (data_fim - timedelta(days=6)).replace(hour=0, minute=0, second=0)
        data_inicio_str = data_inicio.strftime('%Y-%m-%d')
        data_fim_str = data_fim.strftime('%Y-%m-%d')

    operadores = Usuario.query.filter(
        Usuario.perfil.in_(['caixa', 'admin']),
        Usuario.ativo == True
    ).order_by(Usuario.nome).all()

    query = MovimentoCaixa.query.filter(
        MovimentoCaixa.data_abertura.between(data_inicio, data_fim)
    )

    if caixa_selecionado > 0:
        query = query.filter(MovimentoCaixa.usuario_id == caixa_selecionado)

    if status_selecionado != 'todos':
        query = query.filter(MovimentoCaixa.status == status_selecionado)

    movimentos = query.order_by(MovimentoCaixa.data_abertura.desc()).all()

    movimentos_processados = []
    totais_gerais = {
        'total_inicial': 0.0,
        'total_vendas_dinheiro': 0.0,
        'total_vendas_cartao': 0.0,
        'total_vendas_pix': 0.0,
        'total_vendido': 0.0,
        'total_esperado': 0.0,
        'total_informado': 0.0,
        'total_diferenca': 0.0,
        'qtd_caixas_fechados': 0
    }

    for mov in movimentos:
        data_limite = mov.data_fechamento if mov.data_fechamento else datetime.now()
        
        vendas_resumo = db.session.query(
            func.sum(Venda.valor_dinheiro - Venda.troco).label('dinheiro'),
            func.sum(Venda.valor_cartao).label('cartao'),
            func.sum(Venda.valor_pix).label('pix'),
            func.count(Venda.id).label('qtd_vendas')
        ).filter(
            Venda.data_venda >= mov.data_abertura,
            Venda.data_venda <= data_limite,
            Venda.usuario_id == mov.usuario_id,
            Venda.status == 'finalizada'
        ).first()
        
        dinheiro = float(vendas_resumo.dinheiro or 0.0)
        cartao = float(vendas_resumo.cartao or 0.0)
        pix = float(vendas_resumo.pix or 0.0)
        total_vendas = dinheiro + cartao + pix
        qtd_vendas = int(vendas_resumo.qtd_vendas or 0)
        
        saldo_esperado = mov.saldo_inicial + dinheiro
        diferenca = 0.0
        if mov.status == 'fechado':
            diferenca = (mov.saldo_final or 0.0) - saldo_esperado
            totais_gerais['total_informado'] += (mov.saldo_final or 0.0)
            totais_gerais['total_diferenca'] += diferenca
            totais_gerais['qtd_caixas_fechados'] += 1
            
        totais_gerais['total_inicial'] += mov.saldo_inicial
        totais_gerais['total_vendas_dinheiro'] += dinheiro
        totais_gerais['total_vendas_cartao'] += cartao
        totais_gerais['total_vendas_pix'] += pix
        totais_gerais['total_vendido'] += total_vendas
        totais_gerais['total_esperado'] += saldo_esperado

        movimentos_processados.append({
            'id': mov.id,
            'operador': mov.usuario.nome,
            'status': mov.status,
            'data_abertura': mov.data_abertura,
            'data_fechamento': mov.data_fechamento,
            'saldo_inicial': mov.saldo_inicial,
            'saldo_final': mov.saldo_final,
            'vendas_dinheiro': dinheiro,
            'vendas_cartao': cartao,
            'vendas_pix': pix,
            'total_vendas': total_vendas,
            'qtd_vendas': qtd_vendas,
            'saldo_esperado': saldo_esperado,
            'diferenca': diferenca
        })

    return render_template(
        'relatorio_fechamento_caixa.html',
        movimentos=movimentos_processados,
        operadores=operadores,
        data_inicio=data_inicio_str,
        data_fim=data_fim_str,
        caixa_selecionado=caixa_selecionado,
        status_selecionado=status_selecionado,
        totais_gerais=totais_gerais
    )

@app.route('/relatorios/fechamento_caixa/exportar')
@login_required
def exportar_relatorio_fechamento_caixa():
    """Gera e baixa uma planilha Excel com os dados do relatório de fechamento de caixas"""
    if not current_user.is_admin():
        flash('Acesso não autorizado!', 'danger')
        return redirect(url_for('vendas'))

    data_inicio_str = request.args.get('inicio')
    data_fim_str = request.args.get('fim')
    caixa_id_str = request.args.get('caixa_id', '0')
    caixa_selecionado = int(caixa_id_str)
    status_selecionado = request.args.get('status', 'todos')

    hoje_local = date.today()
    if not data_inicio_str:
        data_inicio_str = (hoje_local - timedelta(days=6)).strftime('%Y-%m-%d')
    if not data_fim_str:
        data_fim_str = hoje_local.strftime('%Y-%m-%d')

    try:
        data_inicio = datetime.strptime(data_inicio_str, '%Y-%m-%d').replace(hour=0, minute=0, second=0)
        data_fim = datetime.strptime(data_fim_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
    except ValueError:
        data_fim = datetime.now().replace(hour=23, minute=59, second=59)
        data_inicio = (data_fim - timedelta(days=6)).replace(hour=0, minute=0, second=0)

    query = MovimentoCaixa.query.filter(
        MovimentoCaixa.data_abertura.between(data_inicio, data_fim)
    )

    if caixa_selecionado > 0:
        query = query.filter(MovimentoCaixa.usuario_id == caixa_selecionado)

    if status_selecionado != 'todos':
        query = query.filter(MovimentoCaixa.status == status_selecionado)

    movimentos = query.order_by(MovimentoCaixa.data_abertura.desc()).all()

    rows = []
    for mov in movimentos:
        data_limite = mov.data_fechamento if mov.data_fechamento else datetime.now()
        
        vendas_resumo = db.session.query(
            func.sum(Venda.valor_dinheiro - Venda.troco).label('dinheiro'),
            func.sum(Venda.valor_cartao).label('cartao'),
            func.sum(Venda.valor_pix).label('pix'),
            func.count(Venda.id).label('qtd_vendas')
        ).filter(
            Venda.data_venda >= mov.data_abertura,
            Venda.data_venda <= data_limite,
            Venda.usuario_id == mov.usuario_id,
            Venda.status == 'finalizada'
        ).first()
        
        dinheiro = float(vendas_resumo.dinheiro or 0.0)
        cartao = float(vendas_resumo.cartao or 0.0)
        pix = float(vendas_resumo.pix or 0.0)
        total_vendas = dinheiro + cartao + pix
        qtd_vendas = int(vendas_resumo.qtd_vendas or 0)
        
        saldo_esperado = mov.saldo_inicial + dinheiro
        diferenca = 0.0
        if mov.status == 'fechado':
            diferenca = (mov.saldo_final or 0.0) - saldo_esperado
            
        rows.append({
            'Operador': mov.usuario.nome,
            'Status': 'Aberto' if mov.status == 'aberto' else 'Fechado',
            'Data Abertura': mov.data_abertura.strftime('%d/%m/%Y %H:%M:%S'),
            'Data Fechamento': mov.data_fechamento.strftime('%d/%m/%Y %H:%M:%S') if mov.data_fechamento else '-',
            'Saldo Inicial (R$)': mov.saldo_inicial,
            'Vendas Dinheiro (R$)': dinheiro,
            'Vendas Cartão (R$)': cartao,
            'Vendas PIX (R$)': pix,
            'Total Vendido (R$)': total_vendas,
            'Nº Vendas': qtd_vendas,
            'Saldo Esperado Dinheiro (R$)': saldo_esperado,
            'Saldo Final Contado (R$)': mov.saldo_final if mov.status == 'fechado' else '-',
            'Diferença (R$)': diferenca if mov.status == 'fechado' else '-'
        })

    df = pd.DataFrame(rows)

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='Fechamentos', index=False)
        worksheet = writer.sheets['Fechamentos']
        
        # Estilização do cabeçalho com openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment
        header_font = Font(name='Arial', size=11, bold=True, color='FFFFFF')
        header_fill = PatternFill(start_color='1E293B', end_color='1E293B', fill_type='solid')
        header_alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        
        for cell in worksheet[1]:
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = header_alignment
            
        # Ajusta a largura das colunas
        for col in worksheet.columns:
            max_len = max(len(str(cell.value or '')) for cell in col)
            col_letter = col[0].column_letter
            worksheet.column_dimensions[col_letter].width = max(max_len + 3, 10)

    output.seek(0)
    
    response = make_response(output.read())
    response.headers['Content-Type'] = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    response.headers['Content-Disposition'] = f'attachment; filename=relatorio_fechamento_caixas_{data_inicio_str}_a_{data_fim_str}.xlsx'
    
    return response

# =============================================================================
#           FIM DA NOVA ROTA (CUPOM FECHAMENTO)
# =============================================================================

# =============================================================================
# INICIALIZAÇÃO DO BANCO DE DADOS
# =============================================================================

def init_db():
    """Inicializa o banco de dados com dados de exemplo"""
    with app.app_context():
        # Cria todas as tabelas
        db.create_all()
        
        # Verifica se já existem usuários
        if not Usuario.query.first():
            # Cria usuário administrador
            admin = Usuario(
                nome='Administrador',
                email='admin@loja.com',
                perfil='admin'
                # O model usará datetime.now() para data_criacao
            )
            admin.set_senha('admin123')
            
            # Cria usuário caixa
            caixa = Usuario(
                nome='Operador Caixa',
                email='caixa@loja.com',
                perfil='caixa'
                # O model usará datetime.now() para data_criacao
            )
            caixa.set_senha('caixa123')
            
            db.session.add(admin)
            db.session.add(caixa)
            
            # Adiciona alguns produtos de exemplo
            produtos_exemplo = [
                Produto(
                    codigo_barras='7891000315507',
                    nome='Arroz Integral 1kg',
                    descricao='Arroz integral tipo 1',
                    preco_venda=6.50,
                    preco_custo=4.20,
                    categoria='Alimentos',
                    estoque_atual=50,
                    estoque_minimo=10
                    # O model usará datetime.now() para data_criacao
                ),
                Produto(
                    codigo_barras='7891000053508',
                    nome='Feijão Carioca 1kg',
                    descricao='Feijão carioca tipo 1',
                    preco_venda=8.90,
                    preco_custo=5.80,
                    categoria='Alimentos',
                    estoque_atual=30,
                    estoque_minimo=15
                ),
                Produto(
                    codigo_barras='7891910000197',
                    nome='Café em Pó 500g',
                    descricao='Café torrado e moído',
                    preco_venda=12.90,
                    preco_custo=8.50,
                    categoria='Alimentos',
                    estoque_atual=20,
                    estoque_minimo=5
                ),
                # Adicionando produto do exemplo da imagem
                Produto(
                    codigo_barras='7898927019217',
                    nome='SALGADINHO DORITOS 28G',
                    descricao='Salgadinho de milho',
                    preco_venda=4.50,
                    preco_custo=2.50,
                    categoria='Salgadinhos',
                    estoque_atual=100,
                    estoque_minimo=20
                )
            ]
            
            for produto in produtos_exemplo:
                db.session.add(produto)
            
            db.session.commit()
            
            print("=" * 50)
            print("BANCO DE DADOS INICIALIZADO COM SUCESSO!")
            print("=" * 50)
            print("Usuários criados:")
            print("Admin: admin@loja.com / admin123")
            print("Caixa: caixa@loja.com / caixa123")
            print("=" * 50)
# =============================================================================
# EXTRATO DE ESTOQUE (MOVIMENTAÇÕES)
# =============================================================================
@app.route('/relatorios/extrato')
@login_required
def extrato_estoque():
    """Rota para o extrato detalhado de entrada e saída de produtos"""
    if not current_user.is_admin():
        flash('Acesso não autorizado!', 'danger')
        return redirect(url_for('vendas'))

    # Filtros
    data_inicio_str = request.args.get('inicio')
    data_fim_str = request.args.get('fim')
    produto_id_str = request.args.get('produto_id', '0')
    tipo_movimento_str = request.args.get('tipo', 'todos')

    produto_selecionado = 0
    try:
        produto_selecionado = int(produto_id_str)
    except ValueError:
        produto_selecionado = 0

    hoje_local = date.today()
    if not data_inicio_str:
        data_inicio_str = (hoje_local - timedelta(days=6)).strftime('%Y-%m-%d')
    if not data_fim_str:
        data_fim_str = hoje_local.strftime('%Y-%m-%d')

    try:
        data_inicio = datetime.strptime(data_inicio_str, '%Y-%m-%d').replace(hour=0, minute=0, second=0)
        data_fim = datetime.strptime(data_fim_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
    except ValueError:
        data_fim = datetime.now().replace(hour=23, minute=59, second=59)
        data_inicio = (data_fim - timedelta(days=6)).replace(hour=0, minute=0, second=0)
        data_inicio_str = data_inicio.strftime('%Y-%m-%d')
        data_fim_str = data_fim.strftime('%Y-%m-%d')

    query = MovimentoEstoque.query.filter(
        MovimentoEstoque.data_movimento.between(data_inicio, data_fim)
    )

    if produto_selecionado > 0:
        query = query.filter(MovimentoEstoque.produto_id == produto_selecionado)
        
    if tipo_movimento_str != 'todos':
        query = query.filter(MovimentoEstoque.tipo_movimento == tipo_movimento_str)

    movimentos = query.order_by(MovimentoEstoque.data_movimento.desc()).all()
    produtos = Produto.query.order_by(Produto.nome).all()

    return render_template('extrato_estoque.html',
                           movimentos=movimentos,
                           data_inicio=data_inicio_str,
                           data_fim=data_fim_str,
                           produtos=produtos,
                           produto_selecionado=produto_selecionado,
                           tipo_selecionado=tipo_movimento_str)

if __name__ == '__main__':
    with app.app_context():
        db_path = os.path.join(app.instance_path, 'loja.db')
        if not os.path.exists(db_path):
            print(f"Banco de dados não encontrado em {db_path}. Inicializando...")
            os.makedirs(app.instance_path, exist_ok=True)
            init_db()
        else:
            print(f"Banco de dados encontrado em {db_path}.")

    # =========================================================
    # SERVIDOR PARA REDE MULTI-PDV
    # =========================================================
    import socket
    hostname = socket.gethostname()
    local_ip = socket.gethostbyname(hostname)
    print("")
    print("=" * 55)
    print("  SISTEMA DE CAIXA - MODO REDE MULTI-PDV")
    print("=" * 55)
    print(f"  Acesse neste computador:  http://localhost:5000")
    print(f"  Acesse em outros PDVs:    http://{local_ip}:5000")
    print("  (outros PDVs devem estar na mesma rede Wi-Fi/LAN)")
    print("=" * 55)
    print("")

    app.run(
        host='0.0.0.0',       # Aceita conexões de qualquer IP da rede
        port=5000,
        debug=False,          # DESLIGADO em produção (mais estável)
        threaded=True,        # Atende múltiplos PDVs simultaneamente
        use_reloader=False,   # Evita dupla inicialização
    )
