from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from database import db
from models import Usuario, Produto, Venda, ItemVenda, MovimentoCaixa
from datetime import datetime, timedelta
import os

def create_app():
    """
    Função factory para criar a aplicação Flask
    """
    app = Flask(__name__)
    
    # Configurações
    app.config['SECRET_KEY'] = 'chave-secreta-desenvolvimento'
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///loja.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
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
    return Usuario.query.get(int(user_id))

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
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    """
    Rota para login de usuários
    """
    # Se o usuário já está logado, redireciona para o dashboard
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        email = request.form.get('email')
        senha = request.form.get('senha')
        
        # Busca usuário pelo email
        usuario = Usuario.query.filter_by(email=email, ativo=True).first()
        
        # Verifica se usuário existe e senha está correta
        if usuario and usuario.check_senha(senha):
            login_user(usuario)
            
            # Redireciona para a página que tentava acessar ou dashboard
            next_page = request.args.get('next')
            if next_page:
                return redirect(next_page)
            return redirect(url_for('dashboard'))
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
    
    return dict(
        caixa_aberto=caixa_aberto,
        movimento_atual=movimento_atual,
        now=datetime.now()
    )

# =============================================================================
# ROTAS PRINCIPAIS
# =============================================================================

@app.route('/dashboard')
@login_required
def dashboard():
    """
    Dashboard principal do sistema
    """
    # Estatísticas para o dashboard
    hoje = datetime.now().date()
    
    # Total vendido hoje
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
    
    # Movimento de caixa atual
    caixa_aberto, movimento_atual = get_caixa_aberto()
    
    return render_template('dashboard.html',
                         total_hoje=total_hoje,
                         estoque_baixo=estoque_baixo,
                         total_produtos=total_produtos,
                         movimento_atual=movimento_atual)

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
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        saldo_inicial = float(request.form.get('saldo_inicial', 0))
        
        # Cria novo movimento de caixa
        novo_caixa = MovimentoCaixa(
            saldo_inicial=saldo_inicial,
            usuario_id=current_user.id,
            status='aberto'
        )
        
        db.session.add(novo_caixa)
        db.session.commit()
        
        flash('Caixa aberto com sucesso!', 'success')
        return redirect(url_for('dashboard'))
    
    return render_template('abrir_caixa.html')

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
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        saldo_final = float(request.form.get('saldo_final', 0))
        
        # Calcula total de vendas do período
        vendas_periodo = Venda.query.filter(
            Venda.data_venda >= movimento_atual.data_abertura,
            Venda.status == 'finalizada'
        ).all()
        
        total_vendas = sum(venda.valor_total for venda in vendas_periodo)
        
        # Atualiza movimento de caixa
        movimento_atual.data_fechamento = datetime.now()
        movimento_atual.saldo_final = saldo_final
        movimento_atual.status = 'fechado'
        
        db.session.commit()
        
        flash(f'Caixa fechado com sucesso! Total de vendas: R$ {total_vendas:.2f}', 'success')
        return redirect(url_for('dashboard'))
    
    # Calcula estatísticas para exibir no fechamento
    vendas_periodo = Venda.query.filter(
        Venda.data_venda >= movimento_atual.data_abertura,
        Venda.status == 'finalizada'
    ).all()
    
    total_vendas = sum(venda.valor_total for venda in vendas_periodo)
    total_vendas_count = len(vendas_periodo)
    
    return render_template('fechar_caixa.html',
                         caixa_aberto=movimento_atual,
                         total_vendas=total_vendas,
                         total_vendas_count=total_vendas_count)

# =============================================================================
# ROTAS DO MENU (ADMIN E PDV)
# =============================================================================

@app.route('/produtos')
@login_required
def produtos():
    """Rota para gerenciamento de produtos (apenas admin)"""
    if not current_user.is_admin():
        flash('Acesso não autorizado!', 'danger')
        return redirect(url_for('dashboard'))
    
    # Placeholder - será implementado depois
    produtos_lista = Produto.query.filter_by(ativo=True).all()
    return render_template('produtos.html', produtos=produtos_lista)

# --- INÍCIO GERENCIAMENTO DE USUÁRIOS (CRUD) ---

@app.route('/usuarios')
@login_required
def usuarios():
    """Rota para gerenciamento de usuários (apenas admin)"""
    if not current_user.is_admin():
        flash('Acesso não autorizado!', 'danger')
        return redirect(url_for('dashboard'))
    
    usuarios_lista = Usuario.query.order_by(Usuario.nome).all()
    # CORREÇÃO: Apontando para 'usuarios.htm'
    return render_template('usuarios.htm', usuarios=usuarios_lista)

@app.route('/usuarios/novo', methods=['GET', 'POST'])
@login_required
def usuarios_novo():
    """Rota para criar novo usuário"""
    if not current_user.is_admin():
        flash('Acesso não autorizado!', 'danger')
        return redirect(url_for('dashboard'))

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
        return redirect(url_for('dashboard'))

    usuario = Usuario.query.get_or_404(id)

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
        return redirect(url_for('dashboard'))

    usuario = Usuario.query.get_or_404(id)

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

@app.route('/relatorios')
@login_required
def relatorios():
    """Rota para relatórios"""
    # Placeholder - será implementado depois
    return render_template('relatorios.html')


# =============================================================================
# ROTAS DO PDV (PONTO DE VENDA) - API
# =============================================================================

@app.route('/api/produto/<string:codigo_barras>')
@login_required
def api_buscar_produto(codigo_barras):
    """
    API para buscar produto pelo código de barras.
    Chamado pelo JavaScript do PDV.
    """
    # Verifica se o caixa está aberto
    caixa_aberto, _ = get_caixa_aberto()
    if not caixa_aberto:
        return jsonify({'error': 'Caixa está fechado!'}), 403
    
    produto = Produto.query.filter_by(codigo_barras=codigo_barras, ativo=True).first()
    
    if not produto:
        return jsonify({'error': 'Produto não encontrado'}), 404
        
    if produto.estoque_atual <= 0:
        return jsonify({'error': f'Produto sem estoque: {produto.nome}'}), 400
        
    return jsonify({
        'id': produto.id,
        'nome': produto.nome,
        'preco_venda': produto.preco_venda,
        'estoque_atual': produto.estoque_atual
    })

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
        
        # Gera o número da venda
        numero_venda = f"V{int(datetime.now().timestamp())}"
        
        # Cria a Venda principal
        nova_venda = Venda(
            numero_venda=numero_venda,
            valor_total=0, # Será calculado
            valor_pago=float(data.get('valor_pago', 0)),
            forma_pagamento=data.get('forma_pagamento', 'dinheiro'),
            status='finalizada',
            usuario_id=current_user.id
        )
        
        # Loop nos itens do carrinho para validar estoque e calcular total
        for item_json in data['itens']:
            produto = Produto.query.get(item_json['id'])
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
            )
            admin.set_senha('admin123')
            
            # Cria usuário caixa
            caixa = Usuario(
                nome='Operador Caixa',
                email='caixa@loja.com',
                perfil='caixa'
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
        db_path = os.path.join(app.instance_path, 'loja.db')
        if not os.path.exists(db_path):
            print("Banco de dados não encontrado. Inicializando...")
            init_db()
        else:
            print("Banco de dados já existe. Pulando inicialização.")
            
    app.run(debug=True, host='0.0.0.0', port=5000)
