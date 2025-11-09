from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from database import db
from sqlalchemy import func, or_ # <-- IMPORTAÇÃO ADICIONADA
from models import Usuario, Produto, Venda, ItemVenda, MovimentoCaixa
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
    
    # ===========================================================
    #           CORREÇÃO DE FUSO (VISUAL)
    # ===========================================================
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
                
                # 1. Busca APENAS as vendas em DINHEIRO daquele período
                #    (Agora comparando hora local com hora local)
                vendas_dinheiro = Venda.query.filter(
                    Venda.data_venda >= ultimo_movimento.data_abertura,
                    Venda.data_venda <= ultimo_movimento.data_fechamento, 
                    Venda.usuario_id == op.id,
                    Venda.status == 'finalizada',
                    Venda.forma_pagamento == 'dinheiro'
                ).all()
                
                # 2. Soma apenas o total em DINHEIRO
                total_vendas_dinheiro = sum(venda.valor_total for venda in vendas_dinheiro)
                
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

    # 2. Agrupa os totais por forma de pagamento
    vendas_agrupadas = db.session.query(
        Venda.forma_pagamento,
        func.sum(Venda.valor_total).label('total')
    ).filter(
        Venda.data_venda >= movimento_atual.data_abertura,
        Venda.data_venda <= datetime.now(), # Filtra até o momento atual
        Venda.usuario_id == current_user.id,
        Venda.status == 'finalizada'
    ).group_by(Venda.forma_pagamento).all()

    # Prepara o dicionário de totais
    totais = {
        'dinheiro': 0.0,
        'cartao': 0.0,
        'pix': 0.0,
        'total_geral': 0.0
    }
    
    for forma, total in vendas_agrupadas:
        if forma in totais:
            totais[forma] = float(total or 0.0)
        totais['total_geral'] += float(total or 0.0)

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
    produtos_lista = Produto.query.order_by(Produto.nome).all()
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
    query_sumario = db.session.query(
        db.func.count(Venda.id).label('num_vendas'),
        db.func.sum(Venda.valor_total).label('total_vendido')
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
    if forma_pgto_selecionada != 'todos':
        query_sumario = query_sumario.filter(Venda.forma_pagamento == forma_pgto_selecionada)

    sumario = query_sumario.first()

    # Cálculo do Ticket Médio
    total_vendido = sumario.total_vendido or 0
    num_vendas = sumario.num_vendas or 0
    ticket_medio = (total_vendido / num_vendas) if num_vendas > 0 else 0

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
    if forma_pgto_selecionada != 'todos':
        query_produtos = query_produtos.filter(Venda.forma_pagamento == forma_pgto_selecionada)

    produtos_vendidos = query_produtos.group_by(Produto.id)\
                                      .order_by(db.func.sum(ItemVenda.quantidade).desc())\
                                      .limit(10)\
                                      .all()

    # --- 3. Consulta de Itens Vendidos (Detalhe) ---
    query_itens = db.session.query(
        ItemVenda
    ).join(Venda, Venda.id == ItemVenda.venda_id)\
     .join(Produto, Produto.id == ItemVenda.produto_id)\
     .filter(
        Venda.status == 'finalizada',
        Venda.data_venda.between(data_inicio, data_fim)
     )
    
    # Aplica filtro de caixa
    if caixa_selecionado > 0:
        query_itens = query_itens.filter(Venda.usuario_id == caixa_selecionado)
        
    # Aplica filtro de forma de pagamento
    if forma_pgto_selecionada != 'todos':
        query_itens = query_itens.filter(Venda.forma_pagamento == forma_pgto_selecionada)

    itens_vendidos_detalhe = query_itens.order_by(Venda.data_venda.desc()).all()


    return render_template('relatorios.html',
                         data_inicio=data_inicio_str,
                         data_fim=data_fim_str,
                         total_vendido=total_vendido,
                         num_vendas=num_vendas,
                         ticket_medio=ticket_medio,
                         produtos_vendidos=produtos_vendidos,
                         itens_vendidos_detalhe=itens_vendidos_detalhe,
                         caixas=caixas, # Envia a lista de caixas para o filtro
                         caixa_selecionado=caixa_selecionado, # Envia o ID do caixa selecionado
                         nome_filtro=nome_filtro, # Envia o nome do filtro
                         forma_pgto_selecionada=forma_pgto_selecionada # Envia a forma de pgto
                         )


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


    # --- 2. EXECUTA A MESMA CONSULTA DE ITENS VENDIDOS ---
    query_itens = db.session.query(
        ItemVenda
    ).join(Venda, Venda.id == ItemVenda.venda_id)\
     .join(Produto, Produto.id == ItemVenda.produto_id)\
     .filter(
        Venda.status == 'finalizada',
        Venda.data_venda.between(data_inicio, data_fim)
     )
    
    if caixa_selecionado > 0:
        query_itens = query_itens.filter(Venda.usuario_id == caixa_selecionado)
    if forma_pgto_selecionada != 'todos':
        query_itens = query_itens.filter(Venda.forma_pagamento == forma_pgto_selecionada)

    itens_vendidos_detalhe = query_itens.order_by(Venda.data_venda.desc()).all()

    # --- 3. PREPARA OS DADOS PARA O PANDAS ---
    dados_para_planilha = []
    for item in itens_vendidos_detalhe:
        dados_para_planilha.append({
            'ID Venda': item.venda.id,
            'Data Venda': item.venda.data_venda.strftime('%Y-%m-%d %H:%M:%S'), # Agora está em hora local
            'Operador': item.venda.operador.nome,
            'Forma Pgto': item.venda.forma_pagamento.title(),
            'ID Produto': item.produto.id,
            'Cód. Barras': item.produto.codigo_barras,
            'Produto': item.produto.nome,
            'Quantidade': item.quantidade,
            'Preço Unit. (R$)': item.preco_unitario,
            'Subtotal (R$)': item.subtotal
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

    # 3. Verifica o resultado da busca
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
    
    # Busca por nome OU código de barras
    produtos_encontrados = Produto.query.filter(
        or_(
            Produto.nome.ilike(filtro_like),
            Produto.codigo_barras.ilike(filtro_like)
        ),
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
        else:
            nova_venda.valor_pago = valor_total_venda # Garante que valor pago é o total
            nova_venda.troco = 0

        # Adiciona os itens à venda (o backref cuida do venda_id)
        nova_venda.itens = itens_venda_db
        
        # Salva tudo no banco
        db.session.add(nova_venda)
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
#           INÍCIO DA NOVA ROTA (CUPOM FECHAMENTO)
# =============================================================================

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
        Venda.data_venda >= movimento_atual.data_abertura,
        Venda.data_venda <= datetime.now(), # CORRIGIDO (era utcnow)
        Venda.usuario_id == current_user.id,
        Venda.status == 'finalizada'
    )
    
    # 2. Total de Vendas (para contagem)
    vendas_periodo = query_vendas.all()
    total_vendas_count = len(vendas_periodo)

    # 3. Agrupa os totais por forma de pagamento
    vendas_agrupadas = db.session.query(
        Venda.forma_pagamento,
        func.sum(Venda.valor_total).label('total')
    ).filter(
        Venda.data_venda >= movimento_atual.data_abertura,
        Venda.data_venda <= datetime.now(), # CORRIGIDO (era utcnow)
        Venda.usuario_id == current_user.id,
        Venda.status == 'finalizada'
    ).group_by(Venda.forma_pagamento).all()

    # 4. Prepara o dicionário de totais
    totais = {
        'dinheiro': 0.0,
        'cartao': 0.0,
        'pix': 0.0,
        'total_geral': 0.0,
        'total_vendas_count': total_vendas_count
    }
    
    for forma, total in vendas_agrupadas:
        if forma in totais:
            totais[forma] = float(total or 0.0)
        totais['total_geral'] += float(total or 0.0)
    
    # O "Saldo Esperado em Dinheiro"
    saldo_esperado_dinheiro = movimento_atual.saldo_inicial + totais['dinheiro']

    return render_template('cupom_fechamento.html', 
                         caixa=movimento_atual,
                         totais=totais,
                         saldo_esperado_dinheiro=saldo_esperado_dinheiro)

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