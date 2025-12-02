from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file
# CORREÇÃO: LoginManager deve ser importado
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from database import db
from sqlalchemy import func, or_, asc
# Importação dos modelos atualizados (incluindo PagamentoVenda)
from models import Usuario, Produto, Venda, ItemVenda, MovimentoCaixa, PagamentoVenda
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
    
    # Configurações
    app.config['SECRET_KEY'] = 'chave-secreta-desenvolvimento'
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///loja.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
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
# FUNÇÕES AUXILIARES PARA TRATAMENTO DE VALORES NUMÉRICOS DE FORMULÁRIO
# Corrigem o TypeError: float() argument must be a string or a real number, not 'tuple'
# =============================================================================
def _get_float_val(key, default=0.0):
    """Tenta obter um valor float de um campo do formulário, tratando campos vazios ou multi-valores."""
    # Usamos getlist para garantir que pegamos o valor mesmo se for inesperadamente 
    # submetido como multi-valor.
    value_list = request.form.getlist(key)
    # Se a lista não estiver vazia, pegamos o primeiro elemento. Senão, usamos o default.
    value = value_list[0] if value_list and value_list[0] else default
    
    try:
        # Tenta converter para float
        return float(value)
    except (ValueError, TypeError):
        # Em caso de falha na conversão, retorna o default (geralmente 0.0)
        return default

def _get_int_val(key, default=0):
    """Tenta obter um valor int de um campo do formulário, tratando campos vazios ou multi-valores."""
    value_list = request.form.getlist(key)
    # Se a lista não estiver vazia, pegamos o primeiro elemento. Senão, usamos o default.
    value = value_list[0] if value_list and value_list[0] else default
    
    try:
        # Tenta converter para int. 
        # Nota: Se o input for '1.5', int('1.5') falha. Se for esse o caso, precisaria de int(float(value)).
        # Por segurança, mantemos a conversão direta e usamos o default em caso de erro, 
        # já que os campos de estoque esperam inteiros.
        return int(value)
    except (ValueError, TypeError):
        # Em caso de falha na conversão, retorna o default (geralmente 0)
        return default

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

@app.context_processor
def inject_context():
    """
    Injeta variáveis em todos os templates
    """
    caixa_aberto = False
    movimento_atual = None
    
    if current_user.is_authenticated:
        caixa_aberto, movimento_atual = get_caixa_aberto()
    
    # Voltando para datetime.now() para usar a HORA LOCAL
    return dict(
        caixa_aberto=caixa_aberto,
        movimento_atual=movimento_atual,
        now=datetime.now() # <-- CORRIGIDO
    )
    # ===========================================================

# =============================================================================
# ROTAS PRINCIPAIS
# =============================================================================

# =============================================================================
#           INÍCIO DA ROTA MODIFICADA (DASHBOARD) - AJUSTE PARA MULTIPAGAMENTO
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

    # Estatísticas para o dashboard
    hoje = date.today()
    
    # Total vendido hoje (Valor total da Venda é uma property calculada em models.py)
    # Usando func.date para comparar apenas a data
    vendas_hoje = Venda.query.filter(
        db.func.date(Venda.data_venda) == hoje,
        Venda.status == 'finalizada'
    ).all()
    # Usa a propriedade 'valor_total' do modelo Venda
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
    hoje_meia_noite_local = datetime.combine(hoje, time.min) 
    caixas_esquecidos = MovimentoCaixa.query.filter(
        MovimentoCaixa.status == 'aberto',
        MovimentoCaixa.data_abertura < hoje_meia_noite_local
    ).order_by(MovimentoCaixa.data_abertura.desc()).all()
    
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
                
                # 1. Soma APENAS os pagamentos em DINHEIRO daquele período usando o novo modelo
                total_dinheiro_movimento = db.session.query(func.sum(PagamentoVenda.valor)).join(Venda).filter(
                    Venda.usuario_id == op.id,
                    Venda.status == 'finalizada',
                    PagamentoVenda.forma_pagamento == 'dinheiro',
                    PagamentoVenda.data_pagamento >= ultimo_movimento.data_abertura,
                    PagamentoVenda.data_pagamento <= ultimo_movimento.data_fechamento 
                ).scalar() or 0.0
                
                # 2. Calcula o saldo esperado (Dinheiro)
                #    (Saldo Inicial + Pagamentos em Dinheiro)
                saldo_esperado = (ultimo_movimento.saldo_inicial or 0) + total_dinheiro_movimento

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

@app.route('/backup_database')
@login_required
def backup_database():
    """
    Permite que o administrador baixe o arquivo do banco de dados.
    """
    if not current_user.is_admin():
        flash('Acesso não autorizado!', 'danger')
        return redirect(url_for('dashboard'))

    try:
        # O banco de dados está na pasta 'instance'
        db_path = os.path.join(app.instance_path, 'loja.db')
        
        if not os.path.exists(db_path):
            flash('Erro: Arquivo do banco de dados não encontrado.', 'danger')
            return redirect(url_for('dashboard'))

        # Gera um nome de arquivo com a data
        data_hoje = datetime.now().strftime('%Y-%m-%d_%H%M')
        nome_arquivo_backup = f'backup_loja_{data_hoje}.db'

        return send_file(db_path, as_attachment=True, download_name=nome_arquivo_backup)

    except Exception as e:
        flash(f'Erro ao gerar o backup: {e}', 'danger')
        return redirect(url_for('dashboard'))


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
        # CORREÇÃO: Usando a função auxiliar para garantir que o valor seja um float/string único
        saldo_inicial = _get_float_val('saldo_inicial')
        
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
#           INÍCIO DA ROTA MODIFICADA (FECHAR CAIXA) - AJUSTE PARA MULTIPAGAMENTO
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
        # CORREÇÃO: Usando a função auxiliar para garantir que o valor seja um float/string único
        saldo_final = _get_float_val('saldo_final')
        
        # 1. Define o momento exato do fechamento UMA VEZ (em HORA LOCAL)
        momento_fechamento = datetime.now() 
        
        # 2. Calcula total de vendas para a mensagem (opcional)
        vendas_periodo_post = Venda.query.filter(
            Venda.data_venda >= movimento_atual.data_abertura, 
            Venda.data_venda <= momento_fechamento, 
            Venda.usuario_id == current_user.id,
            Venda.status == 'finalizada'
        ).all()
        
        # O valor total da venda agora é uma propriedade calculada
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
    
    # 1. Query base das vendas no período (abertura local até agora local)
    query_vendas = Venda.query.filter(
        Venda.usuario_id == current_user.id,
        Venda.status == 'finalizada',
        Venda.data_venda >= movimento_atual.data_abertura,
        Venda.data_venda <= datetime.now() 
    )
    
    # 2. Total de Vendas (para contagem)
    total_vendas_count = query_vendas.count()

    # 3. Agrupa os totais por forma de pagamento (usando PagamentoVenda)
    vendas_agrupadas = db.session.query(
        PagamentoVenda.forma_pagamento,
        func.sum(PagamentoVenda.valor).label('total')
    ).join(Venda).filter(
        Venda.usuario_id == current_user.id,
        Venda.status == 'finalizada',
        PagamentoVenda.data_pagamento >= movimento_atual.data_abertura,
        PagamentoVenda.data_pagamento <= datetime.now()
    ).group_by(PagamentoVenda.forma_pagamento).all()

    # Prepara o dicionário de totais
    totais = {
        'dinheiro': 0.0,
        'cartao': 0.0,
        'pix': 0.0,
        'total_geral': 0.0
    }
    
    for forma, total in vendas_agrupadas:
        forma_str = str(forma).lower()
        
        # Filtra apenas as formas permitidas no PDV
        if forma_str in ['dinheiro', 'cartao', 'pix']:
            totais[forma_str] = float(total or 0.0)
        
        # O total geral deve somar todas as formas, mesmo as descontinuadas
        totais['total_geral'] += float(total or 0.0)

    # O 'saldo_esperado' é o (Saldo Inicial + Vendas em Dinheiro)
    saldo_esperado_dinheiro = (movimento_atual.saldo_inicial or 0) + totais['dinheiro']
    
    # Certifica-se que todos os totais importantes existem para o template
    default_totais = {
        'dinheiro': 0.0,
        'cartao': 0.0,
        'pix': 0.0
    }
    # Atualiza com os valores calculados, mantendo as chaves necessárias
    for key in default_totais.keys():
        default_totais[key] = totais.get(key, 0.0)
    default_totais['total_geral'] = totais['total_geral']

    return render_template('fechar_caixa.html',
                         caixa_aberto=movimento_atual,
                         totais=totais, # Enviando o dict de totais COMPLETO
                         saldo_esperado_dinheiro=saldo_esperado_dinheiro,
                         total_vendas_dinheiro=totais['dinheiro'], 
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
    # CORREÇÃO: Adicionando Produto.id.asc() como ordenação secundária para garantir estabilidade
    produtos_lista = Produto.query.order_by(Produto.nome.asc(), Produto.id.asc()).all()
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

        # CORREÇÃO: Usando as funções auxiliares para extrair e converter valores numéricos com segurança
        novo_produto = Produto(
            codigo_barras=codigo_barras,
            nome=nome,
            descricao=request.form.get('descricao'),
            preco_venda=_get_float_val('preco_venda'),
            preco_custo=_get_float_val('preco_custo'),
            categoria=request.form.get('categoria'),
            estoque_atual=_get_int_val('estoque_atual'),
            estoque_minimo=_get_int_val('estoque_minimo'),
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
        
        # Verifica se o código de barras foi alterado e se o novo já existe
        if codigo_barras_novo != produto.codigo_barras and Produto.query.filter_by(codigo_barras=codigo_barras_novo).first():
             flash('Este código de barras já pertence a outro produto.', 'danger')
             return render_template('produto_form.html', produto=produto)

        produto.codigo_barras = codigo_barras_novo
        produto.nome = request.form.get('nome')
        produto.descricao = request.form.get('descricao')
        # CORREÇÃO: Usando as funções auxiliares para extrair e converter valores numéricos com segurança
        produto.preco_venda = _get_float_val('preco_venda')
        produto.preco_custo = _get_float_val('preco_custo')
        produto.categoria = request.form.get('categoria')
        produto.estoque_atual = _get_int_val('estoque_atual')
        produto.estoque_minimo = _get_int_val('estoque_minimo')
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
                        continue # Pula para a próxima iteração

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
# ROTA DE RELATÓRIOS (ATUALIZADA) - AJUSTE PARA FILTRO DE DATA
# =============================================================================
def get_filtro_datas(request):
    """Função auxiliar para obter e padronizar as datas de filtro (início/fim)"""
    data_inicio_str = request.args.get('inicio')
    data_fim_str = request.args.get('fim')
    hoje_local = date.today()
    
    # Define o padrão (últimos 7 dias) se nenhuma data for fornecida
    if not data_inicio_str:
        data_inicio_str = (hoje_local - timedelta(days=6)).strftime('%Y-%m-%d')
    if not data_fim_str:
        data_fim_str = hoje_local.strftime('%Y-%m-%d')

    try:
        # Converte as strings para objetos datetime (início do dia e fim do dia)
        data_inicio = datetime.strptime(data_inicio_str, '%Y-%m-%d').replace(hour=0, minute=0, second=0)
        data_fim = datetime.strptime(data_fim_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
    except ValueError:
        flash('Formato de data inválido. Usando filtro padrão (últimos 7 dias).', 'danger')
        data_fim = datetime.now().replace(hour=23, minute=59, second=59) 
        data_inicio = (data_fim - timedelta(days=6)).replace(hour=0, minute=0, second=0)
        data_inicio_str = data_inicio.strftime('%Y-%m-%d')
        data_fim_str = data_fim.strftime('%Y-%m-%d')
        
    return data_inicio_str, data_fim_str, data_inicio, data_fim

@app.route('/relatorios')
@login_required
def relatorios():
    """Rota para relatórios (Apenas Admin)"""
    if not current_user.is_admin():
        flash('Acesso não autorizado!', 'danger')
        return redirect(url_for('vendas'))

    # --- Lógica de Filtro de Data e Caixa ---
    data_inicio_str, data_fim_str, data_inicio, data_fim = get_filtro_datas(request)
    
    caixa_id_str = request.args.get('caixa_id', '0') # '0' significa "Todos"
    caixa_selecionado = 0
    try:
        caixa_selecionado = int(caixa_id_str)
    except ValueError:
        caixa_selecionado = 0 

    forma_pgto_selecionada = request.args.get('forma_pgto', 'todos') # 'todos' é o padrão

    # Busca todos os caixas (usuários) para o filtro dropdown
    caixas = Usuario.query.order_by(Usuario.nome).all()
    nome_filtro = "Geral (Todos os Caixas)"

    # Query base para vendas finalizadas no período
    base_query = Venda.query.filter(
        Venda.status == 'finalizada',
        Venda.data_venda.between(data_inicio, data_fim)
    )

    # Aplica filtro de caixa se um específico foi selecionado
    if caixa_selecionado > 0:
        base_query = base_query.filter(Venda.usuario_id == caixa_selecionado)
        usuario_filtro = db.session.get(Usuario, caixa_selecionado)
        if usuario_filtro:
            nome_filtro = f"Caixa: {usuario_filtro.nome}"

    # Query para total vendido e número de vendas
    vendas_filtradas = base_query.all()
    total_vendido = sum(v.valor_total for v in vendas_filtradas)
    num_vendas = len(vendas_filtradas)
    ticket_medio = (total_vendido / num_vendas) if num_vendas > 0 else 0

    # Query para pagamentos (para aplicar o filtro de forma de pagamento)
    query_pagamentos_agrupados = db.session.query(
        PagamentoVenda.forma_pagamento,
        func.sum(PagamentoVenda.valor).label('total_pago')
    ).join(Venda).filter(
        Venda.status == 'finalizada',
        Venda.data_venda.between(data_inicio, data_fim)
    )
    
    # Aplica filtro de caixa para pagamentos
    if caixa_selecionado > 0:
        query_pagamentos_agrupados = query_pagamentos_agrupados.filter(Venda.usuario_id == caixa_selecionado)

    # Aplica filtro de forma de pagamento para o resumo (se não for 'todos')
    if forma_pgto_selecionada != 'todos':
        query_pagamentos_agrupados = query_pagamentos_agrupados.filter(PagamentoVenda.forma_pagamento == forma_pgto_selecionada)


    pagamentos_agrupados = query_pagamentos_agrupados.group_by(PagamentoVenda.forma_pagamento).all()

    # --- 2. Consulta de Produtos Mais Vendidos (APENAS VENDAS FINALIZADAS) ---
    query_produtos = db.session.query(
        Produto.nome,
        Produto.codigo_barras,
        db.func.sum(ItemVenda.quantidade).label('total_quantidade'),
        db.func.sum(ItemVenda.subtotal).label('total_arrecadado')
    ).join(ItemVenda, ItemVenda.produto_id == Produto.id)\
     .join(Venda, Venda.id == ItemVenda.venda_id)\
     .filter(
        Venda.status == 'finalizada', # <-- APENAS FINALIZADAS
        Venda.data_venda.between(data_inicio, data_fim)
     )
    
    # Aplica filtro de caixa
    if caixa_selecionado > 0:
        query_produtos = query_produtos.filter(Venda.usuario_id == caixa_selecionado)

    # Aplica filtro de forma de pagamento (se a venda CONTÉM o pagamento)
    if forma_pgto_selecionada != 'todos':
        query_produtos = query_produtos.join(PagamentoVenda, PagamentoVenda.venda_id == Venda.id)\
                                       .filter(PagamentoVenda.forma_pagamento == forma_pgto_selecionada)


    produtos_vendidos = query_produtos.group_by(Produto.id)\
                                      .order_by(db.func.sum(ItemVenda.quantidade).desc())\
                                      .limit(10)\
                                      .all()

    # --- 3. Consulta de Itens Vendidos (Detalhe) (TODOS OS STATUS) ---
    query_itens = db.session.query(
        ItemVenda
    ).join(Venda, Venda.id == ItemVenda.venda_id)\
     .join(Produto, Produto.id == ItemVenda.produto_id)\
     .filter(
        # Sem filtro de status aqui para mostrar canceladas
        Venda.data_venda.between(data_inicio, data_fim)
     )
    
    # Aplica filtro de caixa
    if caixa_selecionado > 0:
        query_itens = query_itens.filter(Venda.usuario_id == caixa_selecionado)
        
    # Aplica filtro de forma de pagamento
    if forma_pgto_selecionada != 'todos':
        query_itens = query_itens.join(PagamentoVenda, PagamentoVenda.venda_id == Venda.id)\
                                 .filter(PagamentoVenda.forma_pagamento == forma_pgto_selecionada)

    itens_vendidos_detalhe = query_itens.order_by(Venda.data_venda.desc()).all()


    return render_template('relatorios.html',
                         data_inicio=data_inicio_str,
                         data_fim=data_fim_str,
                         total_vendido=total_vendido, # Total apenas de vendas finalizadas
                         num_vendas=num_vendas, # Número apenas de vendas finalizadas
                         ticket_medio=ticket_medio,
                         produtos_vendidos=produtos_vendidos,
                         itens_vendidos_detalhe=itens_vendidos_detalhe,
                         pagamentos_agrupados=pagamentos_agrupados, # Pagamentos agrupados
                         caixas=caixas, # Envia a lista de caixas para o filtro
                         caixa_selecionado=caixa_selecionado, # Envia o ID do caixa selecionado
                         nome_filtro=nome_filtro, # Envia o nome do filtro
                         forma_pgto_selecionada=forma_pgto_selecionada
                         )
# =============================================================================
#           FIM DA ROTA MODIFICADA (RELATÓRIOS)
# =============================================================================


# =============================================================================
#           NOVA ROTA: RELATÓRIO CONSOLIDADO DE RECEBIMENTOS POR FORMA
# =============================================================================
@app.route('/relatorios/recebimentos_consolidados')
@login_required
def relatorio_recebimentos_consolidados():
    """
    Nova Rota para relatório consolidado de recebimentos por Forma de Pagamento e por Caixa (Operador).
    """
    if not current_user.is_admin():
        flash('Acesso não autorizado!', 'danger')
        return redirect(url_for('vendas'))

    # 1. Obter e processar datas de filtro (usando a função auxiliar)
    data_inicio_str, data_fim_str, data_inicio, data_fim = get_filtro_datas(request)
    
    # 2. Obter caixas para o dropdown
    caixas = Usuario.query.order_by(Usuario.nome).all()
    
    # 3. Consulta principal: Agrupar por FORMA DE PAGAMENTO e por OPERADOR
    # O SQLalchemy precisa que a coluna PagamentoVenda.forma_pagamento seja acessível
    # É necessário fazer 3 JOINS: PagamentoVenda -> Venda -> Usuario
    
    query_recebimentos = db.session.query(
        PagamentoVenda.forma_pagamento,
        Usuario.nome.label('operador_nome'),
        func.sum(PagamentoVenda.valor).label('total_pago')
    ).join(Venda, Venda.id == PagamentoVenda.venda_id)\
     .join(Usuario, Usuario.id == Venda.usuario_id)\
     .filter(
        Venda.status == 'finalizada', # Apenas vendas finalizadas
        PagamentoVenda.data_pagamento.between(data_inicio, data_fim)
     )
     
    # Aplica filtro de caixa (se selecionado)
    caixa_id_str = request.args.get('caixa_id', '0')
    caixa_selecionado = 0
    try:
        caixa_selecionado = int(caixa_id_str)
    except ValueError:
        caixa_selecionado = 0
        
    if caixa_selecionado > 0:
        query_recebimentos = query_recebimentos.filter(Venda.usuario_id == caixa_selecionado)
    
    # Aplica agrupamento
    query_recebimentos = query_recebimentos.group_by(
        PagamentoVenda.forma_pagamento, 
        Usuario.nome
    ).order_by(Usuario.nome, PagamentoVenda.forma_pagamento).all()


    # 4. Processar resultados para o template (Calculando Totais e Agrupando por Operador)
    
    # Estrutura final: { 'operador': [{'forma': 'Dinheiro', 'total': 100.00}, ...], 'totais_gerais': {...} }
    dados_relatorio = {}
    totais_gerais = {
        'total_dinheiro': 0.0,
        'total_cartao': 0.0,
        'total_pix': 0.0,
        'total_outros': 0.0,
        'total_global': 0.0
    }

    # As formas principais que queremos destacar
    formas_principais = ['dinheiro', 'cartao', 'pix']

    for forma, operador_nome, total_pago in query_recebimentos:
        # Inicializa o operador no dicionário, se necessário
        if operador_nome not in dados_relatorio:
            dados_relatorio[operador_nome] = {f'total_{f}': 0.0 for f in formas_principais}
            dados_relatorio[operador_nome]['outros'] = 0.0
            dados_relatorio[operador_nome]['total_operador'] = 0.0
            dados_relatorio[operador_nome]['detalhes'] = [] # Para formas extras

        forma_lower = forma.lower()
        valor = float(total_pago or 0.0)

        # Soma no total geral
        totais_gerais['total_global'] += valor
        
        # Soma no total do operador
        dados_relatorio[operador_nome]['total_operador'] += valor

        # Soma nas categorias específicas
        if forma_lower in formas_principais:
            totais_gerais[f'total_{forma_lower}'] += valor
            dados_relatorio[operador_nome][f'total_{forma_lower}'] += valor
        else:
            totais_gerais['total_outros'] += valor
            dados_relatorio[operador_nome]['outros'] += valor
            # Adiciona forma de pagamento extra no detalhe
            dados_relatorio[operador_nome]['detalhes'].append({'forma': forma.title(), 'valor': valor})


    return render_template('relatorio_recebimentos_consolidados.html',
                         data_inicio=data_inicio_str,
                         data_fim=data_fim_str,
                         caixas=caixas,
                         caixa_selecionado=caixa_selecionado,
                         dados_relatorio=dados_relatorio,
                         totais_gerais=totais_gerais
                         )
# =============================================================================
#           FIM DA NOVA ROTA (RELATÓRIO CONSOLIDADO DE RECEBIMENTOS)
# =============================================================================


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


# =============================================================================
# ROTA DE RELATÓRIO DE CUPONS (ATUALIZADA)
# =============================================================================
@app.route('/relatorio_cupons')
@login_required
def relatorio_cupons():
    """Rota para relatório de cupons/vendas individuais (Apenas Admin)"""
    if not current_user.is_admin():
        flash('Acesso não autorizado!', 'danger')
        return redirect(url_for('vendas'))

    # --- 1. Lógica de Filtro de Data ---
    data_inicio_str, data_fim_str, data_inicio, data_fim = get_filtro_datas(request)
    
    # --- 2. Lógica de Filtro de Caixa (Usuário) ---
    caixa_id_str = request.args.get('caixa_id', '0') # '0' significa "Todos"
    caixa_selecionado = 0
    try:
        caixa_selecionado = int(caixa_id_str)
    except ValueError:
        caixa_selecionado = 0 

    # --- 3. Lógica de Filtro de Forma de Pagamento ---
    forma_pgto_selecionada = request.args.get('forma_pgto', 'todos') # 'todos' é o padrão

    # --- 5. Busca caixas e nome do filtro ---
    caixas = Usuario.query.order_by(Usuario.nome).all()
    nome_filtro = "Geral (Todos os Caixas)"

    # --- 6. Consulta Principal (Vendas/Cupons) ---
    # Começamos com a query base, já filtrando por status 'finalizada' e datas
    base_query = db.session.query(Venda).join(Usuario).filter(
        Venda.status == 'finalizada',
        Venda.data_venda.between(data_inicio, data_fim)
    )

    # Aplica filtro de caixa se um específico foi selecionado
    if caixa_selecionado > 0:
        base_query = base_query.filter(Venda.usuario_id == caixa_selecionado)
        usuario_filtro = db.session.get(Usuario, caixa_selecionado)
        if usuario_filtro:
            nome_filtro = f"Caixa: {usuario_filtro.nome}"

    # Aplica filtro de forma de pagamento (se a venda CONTÉM o pagamento)
    if forma_pgto_selecionada != 'todos':
        # Faz um JOIN com PagamentoVenda para filtrar as vendas que têm aquele pagamento
        base_query = base_query.join(PagamentoVenda, PagamentoVenda.venda_id == Venda.id)\
                               .filter(PagamentoVenda.forma_pagamento == forma_pgto_selecionada)


    # Executa a query para obter a lista de vendas (cupons)
    vendas_lista = base_query.order_by(Venda.data_venda.desc()).all()
    
    # CORREÇÃO DE ERRO: Serialização explícita para evitar Undefined/Não-serializáveis no template.
    vendas_lista_serializada = []
    for venda in vendas_lista:
        # Serializa os pagamentos aninhados
        pagamentos_serializados = []
        for p in venda.pagamentos:
            pagamentos_serializados.append({
                'forma': str(p.forma_pagamento),
                'valor': float(p.valor or 0.0),
                'data': p.data_pagamento.strftime('%Y-%m-%d %H:%M:%S') if p.data_pagamento else None
            })

        vendas_lista_serializada.append({
            'id': venda.id,
            'numero_venda': venda.numero_venda,
            # Garante que data_venda seja string para serialização JSON
            'data_venda': venda.data_venda.strftime('%Y-%m-%d %H:%M:%S'), 
            'status': str(venda.status),
            'operador': venda.operador.nome,
            'valor_total': float(venda.valor_total),
            'valor_pago': float(venda.valor_pago),
            'troco': float(venda.troco),
            'pagamentos': pagamentos_serializados,
        })
    # FIM CORREÇÃO DE ERRO
    
    # Calcula o total geral dos cupons filtrados (usando a propriedade dinâmica valor_total)
    total_geral_cupons = sum(v.valor_total for v in vendas_lista)

    return render_template('relatorio_cupons.html',
                         vendas_lista=vendas_lista,
                         vendas_lista_serializada=vendas_lista_serializada, # Variável serializada para JS
                         total_geral_cupons=total_geral_cupons,
                         data_inicio=data_inicio_str,
                         data_fim=data_fim_str,
                         caixas=caixas, 
                         caixa_selecionado=caixa_selecionado,
                         nome_filtro=nome_filtro,
                         forma_pgto_selecionada=forma_pgto_selecionada
                         )
# =============================================================================
#           FIM DA ROTA (CUPONS)
# =============================================================================

# =============================================================================
#           INÍCIO DA NOVA ROTA (EXPORTAR EXCEL) - AJUSTE PARA MULTIPAGAMENTO
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
    data_inicio_str, data_fim_str, data_inicio, data_fim = get_filtro_datas(request)
    
    caixa_id_str = request.args.get('caixa_id', '0')
    caixa_selecionado = 0
    try:
        caixa_selecionado = int(caixa_id_str)
    except ValueError:
        caixa_selecionado = 0 
    forma_pgto_selecionada = request.args.get('forma_pgto', 'todos')
    # --- FIM DA LÓGICA DE FILTRO ---


    # Consulta Venda e Itens de Venda
    vendas_com_itens = Venda.query.filter(
        Venda.status.in_(['finalizada', 'cancelada']), # Inclui canceladas para relatório de itens
        Venda.data_venda.between(data_inicio, data_fim)
    )

    if caixa_selecionado > 0:
        vendas_com_itens = vendas_com_itens.filter(Venda.usuario_id == caixa_selecionado)
    
    # Se há filtro de pagamento, filtramos as vendas antes de iterar
    if forma_pgto_selecionada != 'todos':
        vendas_com_itens = vendas_com_itens.join(PagamentoVenda, PagamentoVenda.venda_id == Venda.id)\
                                           .filter(PagamentoVenda.forma_pagamento == forma_pgto_selecionada)


    vendas_lista_final = vendas_com_itens.order_by(Venda.data_venda.desc()).all()


    dados_para_planilha = []
    for venda in vendas_lista_final:
        # Pega as informações de pagamento uma única vez para a venda
        pagamentos_info = {}
        # CORREÇÃO: Apenas as formas principais permitidas no PDV
        formas_colunas = {
            'dinheiro': 0.0,
            'cartao': 0.0,
            'pix': 0.0,
        }
        outras_formas = []
        
        for p in venda.pagamentos:
            forma_lower = p.forma_pagamento.lower()
            valor = p.valor or 0.0
            
            if forma_lower in formas_colunas:
                formas_colunas[forma_lower] += valor
            else:
                # Todas as outras (incluindo transferencia e cheque) vão para "Outras Formas"
                outras_formas.append(f"{p.forma_pagamento.title()}: R$ {valor:.2f}")

        row = {
            'ID Venda': venda.id,
            'Nº Venda': venda.numero_venda,
            'Data Venda': venda.data_venda.strftime('%Y-%m-%d %H:%M:%S'),
            'Status Venda': venda.status.title(),
            'Operador': venda.operador.nome,
            'Valor Total Venda (R$)': venda.valor_total,
            'Valor Pago Total (R$)': venda.valor_pago,
            'Troco Venda (R$)': venda.troco,
            
            # Detalhamento de Pagamentos (Apenas Dinheiro, Cartão e PIX como colunas principais)
            'Dinheiro (R$)': formas_colunas['dinheiro'],
            'Cartão (R$)': formas_colunas['cartao'],
            'PIX (R$)': formas_colunas['pix'],
            'Outras Formas': ", ".join(outras_formas), # Lista as outras formas em uma coluna
            
            'ID Item': '',
            'ID Produto': '',
            'Cód. Barras Produto': '',
            'Produto': '',
            'Quantidade': '',
            'Preço Unit. (R$)': '',
            'Subtotal Item (R$)': ''
        }
        dados_para_planilha.append(row.copy()) # Adiciona a linha da venda (header)
        
        # Adiciona as linhas dos itens de venda
        for item in venda.itens:
             item_row = row.copy() # Copia as informações da venda
             
             # Zera os totais (para que eles apareçam apenas na linha "Header" da venda)
             item_row['Valor Total Venda (R$)'] = ''
             item_row['Valor Pago Total (R$)'] = ''
             item_row['Troco Venda (R$)'] = ''
             item_row['Dinheiro (R$)'] = ''
             item_row['Cartão (R$)'] = ''
             item_row['PIX (R$)'] = ''
             item_row['Outras Formas'] = ''
             
             # Preenche os detalhes do item
             item_row['ID Item'] = item.id
             item_row['ID Produto'] = item.produto.id
             item_row['Cód. Barras Produto'] = item.produto.codigo_barras
             item_row['Produto'] = item.produto.nome
             item_row['Quantidade'] = item.quantidade
             item_row['Preço Unit. (R$)'] = item.preco_unitario
             item_row['Subtotal Item (R$)'] = item.subtotal
             
             dados_para_planilha.append(item_row)

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
    data_formatada = datetime.now().strftime('%Y%m%d_%H%M%S')
    nome_arquivo = f"Relatorio_Det_Vendas_{data_formatada}.xlsx"
    
    response = make_response(output.read())
    response.headers["Content-Disposition"] = f"attachment; filename={nome_arquivo}"
    response.headers["Content-type"] = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    
    return response

# =============================================================================
#           FIM DA ROTA (EXPORTAR EXCEL)
# =============================================================================

@app.route('/vendas/editar_pagamento/<int:venda_id>', methods=['POST'])
@login_required
def editar_pagamento(venda_id):
    """
    Rota para corrigir a forma de pagamento de uma venda já finalizada.
    Apenas administradores podem realizar essa ação.
    Se a venda tem mais de um pagamento, a edição é bloqueada (para forçar cancelamento/re-lançamento).
    """
    if not current_user.is_admin():
        flash('Acesso negado: Apenas administradores podem alterar vendas.', 'danger')
        return redirect(url_for('relatorios'))

    venda = db.session.get(Venda, venda_id)
    
    if not venda:
        flash('Venda não encontrada.', 'danger')
        return redirect(url_for('relatorios', **request.args))
    
    if venda.status == 'cancelada':
        flash('Não é possível editar uma venda cancelada.', 'warning')
        return redirect(url_for('relatorios', **request.args))
    
    # Regra Simplificada: Só permite edição fácil se houver EXATAMENTE UM pagamento
    if len(venda.pagamentos) != 1:
        flash('Edição direta de forma de pagamento bloqueada para vendas com múltiplos pagamentos ou nenhum. Cancele e refaça a venda, ou edite os pagamentos diretamente no banco se necessário.', 'danger')
        return redirect(url_for('relatorios', **request.args))


    nova_forma = request.form.get('nova_forma_pagamento')
    
    # ALTERAÇÃO: Removido 'transferencia' e 'cheque' das formas válidas
    formas_permitidas = ['dinheiro', 'cartao', 'pix']
    if nova_forma in formas_permitidas:
        
        pagamento_unico = venda.pagamentos[0]
        forma_antiga = pagamento_unico.forma_pagamento
        valor_antigo = pagamento_unico.valor

        # Atualiza o pagamento único
        pagamento_unico.forma_pagamento = nova_forma
        
        # Se era dinheiro e mudou, e o valor pago era maior que o total, 
        # forçamos o valor do pagamento para ser o total da venda.
        if forma_antiga == 'dinheiro' and pagamento_unico.valor > venda.valor_total:
             pagamento_unico.valor = venda.valor_total
        
        # Recalcula as propriedades dinâmicas (valor_pago e troco) e salva.
        db.session.commit()
        
        # A mensagem de flash deve ser mais informativa sobre o que realmente foi alterado
        flash(f'Venda #{venda.numero_venda} (Pagamento Único) alterada de {forma_antiga.title()} (R$ {valor_antigo:.2f}) para {nova_forma.title()} (R$ {pagamento_unico.valor:.2f}).', 'success')
    else:
        # Se a forma for uma das removidas (transferencia/cheque) ou inválida
        flash('Forma de pagamento inválida ou não permitida para edição rápida (Apenas Dinheiro, Cartão, PIX).', 'danger')

    # Passa os argumentos de filtro de volta para a URL do relatorio
    return redirect(url_for('relatorios', 
                          inicio=request.args.get('inicio'),
                          fim=request.args.get('fim'),
                          caixa_id=request.args.get('caixa_id'),
                          forma_pgto=request.args.get('forma_pgto')
                          ))

@app.route('/vendas/cancelar/<int:venda_id>', methods=['POST'])
@login_required
def vendas_cancelar(venda_id):
    """
    Rota para cancelar uma venda finalizada (estorno).
    Apenas administradores podem realizar essa ação.
    """
    if not current_user.is_admin():
        flash('Acesso negado: Apenas administradores podem cancelar vendas.', 'danger')
        return redirect(url_for('relatorios'))

    venda = db.session.get(Venda, venda_id)

    if not venda:
        flash('Venda não encontrada.', 'danger')
        return redirect(url_for('relatorios', **request.args))
    
    if venda.status == 'cancelada':
        flash('Esta venda já foi cancelada.', 'info')
        return redirect(url_for('relatorios', **request.args))

    try:
        # Inicia a transação
        
        # 1. Devolve os itens ao estoque
        for item in venda.itens:
            produto = item.produto # Carrega o produto associado
            if produto:
                produto.estoque_atual += item.quantidade
        
        # 2. Marca a venda como "cancelada"
        venda.status = 'cancelada'
        
        db.session.commit()
        flash(f'Venda #{venda.numero_venda} foi cancelada com sucesso. O estoque foi devolvido.', 'success')

    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao cancelar a venda: {str(e)}', 'danger')
    
    # Redireciona de volta para a tela de relatórios com os filtros
    return redirect(url_for('relatorios', 
                          inicio=request.args.get('inicio'),
                          fim=request.args.get('fim'),
                          caixa_id=request.args.get('caixa_id'),
                          forma_pgto=request.args.get('forma_pgto')
                          ))

@app.route('/caixa/cupom_fechamento')
@login_required
def cupom_fechamento():
    """
    Gera um cupom/relatório de fechamento para o caixa ABERTO atual.
    """
    caixa_aberto, movimento_atual = get_caixa_aberto()
    
    if not caixa_aberto:
        flash('Não há caixa aberto para gerar relatório.', 'warning')
        if current_user.is_admin():
            return redirect(url_for('dashboard'))
        return redirect(url_for('vendas'))

    # --- Recalcula os totais para o cupom ---
    
    # 1. Query base das vendas no período (abertura local até agora local)
    query_vendas = Venda.query.filter(
        Venda.usuario_id == current_user.id,
        Venda.status == 'finalizada',
        Venda.data_venda >= movimento_atual.data_abertura,
        Venda.data_venda <= datetime.now() 
    )
    
    # 2. Total de Vendas (para contagem)
    vendas_periodo = query_vendas.all()
    total_vendas_count = len(vendas_periodo)

    # 3. Agrupa os totais por forma de pagamento (usando PagamentoVenda)
    vendas_agrupadas = db.session.query(
        PagamentoVenda.forma_pagamento,
        func.sum(PagamentoVenda.valor).label('total')
    ).join(Venda).filter(
        Venda.usuario_id == current_user.id,
        Venda.status == 'finalizada',
        PagamentoVenda.data_pagamento >= movimento_atual.data_abertura,
        PagamentoVenda.data_pagamento <= datetime.now()
    ).group_by(PagamentoVenda.forma_pagamento).all()

    # 4. Prepara o dicionário de totais (incluindo tratamento de outras formas)
    totais = {
        'dinheiro': 0.0,
        'cartao': 0.0,
        'pix': 0.0,
        'outros': 0.0,
        'total_geral': 0.0
    }
    
    for forma, total in vendas_agrupadas:
        valor = float(total or 0.0)
        totais['total_geral'] += valor
        
        forma_lower = str(forma).lower()
        if forma_lower in totais and forma_lower != 'outros' and forma_lower != 'total_geral':
            totais[forma_lower] = valor
        elif forma_lower not in ['dinheiro', 'cartao', 'pix', 'total_geral']:
             # Soma em 'outros' se não for uma das 3 principais
            totais['outros'] += valor

    # O "Saldo Esperado em Dinheiro"
    saldo_esperado_dinheiro = (movimento_atual.saldo_inicial or 0) + totais['dinheiro']

    return render_template('cupom_fechamento.html', 
                         caixa=movimento_atual,
                         totais=totais,
                         saldo_esperado_dinheiro=saldo_esperado_dinheiro)


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

    # 3. Verifica o resultado da busca
    if not produto:
        return jsonify({'error': 'Produto não encontrado'}), 404
        
    if produto.estoque_atual <= 0:
        return jsonify({'error': f'Produto sem estoque: {produto.nome}'}), 400
        
    # GERA A URL DA IMAGEM SE ELA EXISTIR
    imagem_path = None
    # CORREÇÃO: Verifica explicitamente se a imagem_url é uma string para evitar TypeError de objetos Undefined
    if isinstance(produto.imagem_url, str) and produto.imagem_url:
        # Usa url_for para gerar o caminho correto
        # .replace('static/', '', 1) é usado porque a URL salva no BD é 'static/uploads/produtos/...'
        # mas url_for('static', filename=...) precisa apenas de 'uploads/produtos/...'
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
    
    # Busca por nome OU código de barras
    produtos_encontrados = Produto.query.filter(
        or_(
            Produto.nome.ilike(filtro_like),
            Produto.codigo_barras.ilike(filtro_like)
        ),
        Produto.ativo == True
    # CORREÇÃO: Adicionando Produto.id.asc() como ordenação secundária para garantir estabilidade
    ).order_by(Produto.nome.asc(), Produto.id.asc()).limit(20).all() # Limita a 20 resultados

    # Formata os resultados
    resultados_json = []
    for produto in produtos_encontrados:
        imagem_path = None
        # CORREÇÃO: Verifica explicitamente se a imagem_url é uma string para evitar TypeError de objetos Undefined
        if isinstance(produto.imagem_url, str) and produto.imagem_url:
            # Usa url_for para gerar o caminho correto
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
#           INÍCIO DA ROTA ALTERADA (FINALIZAR VENDA) - MULTIPAGAMENTO
# =============================================================================
@app.route('/vendas/finalizar', methods=['POST'])
@login_required
def finalizar_venda():
    """
    API para finalizar a venda.
    Recebe os dados do carrinho e múltiplos pagamentos via JSON.
    """
    # Verifica se o caixa está aberto
    caixa_aberto, movimento_atual = get_caixa_aberto()
    if not caixa_aberto:
        return jsonify({'error': 'Caixa está fechado!'}), 403

    # Pega os dados enviados pelo JavaScript
    data = request.get_json()
    
    if not data or 'itens' not in data or not data['itens']:
        return jsonify({'error': 'Carrinho vazio'}), 400
    
    if 'pagamentos' not in data or not data['pagamentos']:
        return jsonify({'error': 'Nenhuma forma de pagamento informada.'}), 400

    try:
        # Inicia a transação
        
        valor_total_venda = 0
        itens_venda_db = []
        formas_permitidas_pdv = ['dinheiro', 'cartao', 'pix']
        
        # 1. Loop nos itens do carrinho para validar estoque e calcular total
        for item_json in data['itens']:
            produto = db.session.get(Produto, item_json['id']) 
            quantidade = int(item_json['quantidade'])
            
            if not produto:
                raise Exception(f'Produto ID {item_json["id"]} não encontrado.')
                
            # Verifica o estoque disponível no banco (Produto.estoque_atual)
            if produto.estoque_atual < quantidade:
                # Se for o caso, pode ser uma falha de concorrência ou cache. Rejeita.
                raise Exception(f'Estoque insuficiente para {produto.nome}. (Disponível: {produto.estoque_atual})')


            # Atualiza estoque (apenas em memória por enquanto)
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

        # 2. Cria a Venda principal e calcula o total
        nova_venda = Venda(
            numero_venda="PENDENTE", 
            data_venda=datetime.now(),
            status='finalizada',
            usuario_id=current_user.id
        )
        nova_venda.itens = itens_venda_db
        db.session.add(nova_venda)

        # 3. Processa e adiciona os pagamentos
        pagamentos_db = []
        valor_pago_total = 0.0
        
        # O flush aqui é necessário para que PagamentoVenda possa fazer referência à nova_venda.id, mas
        # como Venda.id é gerado apenas no flush, e PagamentoVenda faz um backref, o flush pode ser após a venda ser adicionada.
        db.session.flush()

        for pagamento_json in data['pagamentos']:
            forma = pagamento_json['forma_pagamento']
            
            # ALTERAÇÃO: Garante que a forma de pagamento enviada pelo PDV seja permitida
            if forma not in formas_permitidas_pdv:
                 # Isso só deve acontecer se o frontend foi modificado para enviar uma opção descontinuada.
                 raise Exception(f"Forma de pagamento '{forma}' não é permitida no PDV.")
            
            valor = float(pagamento_json['valor'])
            valor_pago_total += valor
            
            novo_pagamento = PagamentoVenda(
                venda_id=nova_venda.id,
                forma_pagamento=forma,
                valor=valor,
                data_pagamento=datetime.now()
            )
            pagamentos_db.append(novo_pagamento)
        
        db.session.add_all(pagamentos_db)
        
        # Validação do valor pago vs valor total da venda
        if round(valor_pago_total, 2) < round(valor_total_venda, 2):
            # Se o pagamento for insuficiente, cancela a transação e reverte o estoque.
            db.session.rollback()
            return jsonify({'error': 'Valor total pago insuficiente para o valor total da venda.'}), 400
        
        # O cálculo do troco é automático (propriedade dinâmica) no modelo Venda
        
        # 4. MÁGICA DO SEQUENCIAL: (O flush foi feito, agora atualiza numero_venda e comita)
        nova_venda.numero_venda = str(nova_venda.id) 
        
        # 5. Salva tudo no banco definitivamente
        db.session.commit()
        
        # Usa as propriedades dinâmicas para a resposta
        troco_final = nova_venda.troco

        return jsonify({
            'success': f'Venda finalizada com sucesso! Troco: R$ {troco_final:.2f}',
            'venda_id': nova_venda.id,
            'numero_venda': nova_venda.numero_venda
        })

    except Exception as e:
        db.session.rollback() # Desfaz qualquer mudança no banco em caso de erro
        # Retorna o erro específico (stock, valor pago, ou outro)
        return jsonify({'error': str(e)}), 400
# =============================================================================
#           FIM DA ROTA ALTERADA (FINALIZAR VENDA)
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

if __name__ == '__main__':
    # Garante que o init_db() rode dentro do contexto da app
    with app.app_context():
        # Verifica se o banco de dados já existe antes de inicializar
        # CORREÇÃO: o app.instance_path é o local correto para o 'loja.db'
        db_path = os.path.join(app.instance_path, 'loja.db')
        if not os.path.exists(db_path):
            print(f"Banco de dados não encontrado em {db_path}. Inicializando...")
            # Cria o diretório 'instance' se não existir
            os.makedirs(app.instance_path, exist_ok=True)
            init_db()
        else:
            print(f"Banco de dados encontrado em {db_path}. Pulando inicialização.")
            
    app.run(debug=True, host='0.0.0.0', port=5000)