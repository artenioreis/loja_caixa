from database import db
from flask_login import UserMixin
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import func

class Usuario(db.Model, UserMixin):
    # ... (código do Usuário existente - sem alteração) ...
    __tablename__ = 'usuarios'
    
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    senha_hash = db.Column(db.String(200), nullable=False)
    perfil = db.Column(db.String(20), nullable=False)  # 'admin' ou 'caixa'
    ativo = db.Column(db.Boolean, default=True)
    data_criacao = db.Column(db.DateTime, default=datetime.now) # Era utcnow
    
    # Relacionamento com vendas
    vendas = db.relationship('Venda', backref='operador', lazy=True)
    
    def set_senha(self, senha):
        """Gera hash da senha"""
        self.senha_hash = generate_password_hash(senha)
    
    def check_senha(self, senha):
        """Verifica se a senha está correta"""
        return check_password_hash(self.senha_hash, senha)
    
    def is_admin(self):
        """Verifica se o usuário é administrador"""
        return self.perfil == 'admin'

class Produto(db.Model):
    """
    Modelo para produtos do estoque
    """
    __tablename__ = 'produtos'
    
    id = db.Column(db.Integer, primary_key=True)
    codigo_barras = db.Column(db.String(50), unique=True, nullable=False)
    nome = db.Column(db.String(200), nullable=False)
    descricao = db.Column(db.Text)
    preco_venda = db.Column(db.Float, nullable=False)
    preco_custo = db.Column(db.Float, nullable=False)
    categoria = db.Column(db.String(100))
    estoque_atual = db.Column(db.Integer, default=0)
    estoque_minimo = db.Column(db.Integer, default=0)
    ativo = db.Column(db.Boolean, default=True)
    data_criacao = db.Column(db.DateTime, default=datetime.now) # Era utcnow
    data_atualizacao = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now) # Era utcnow
    
    # NOVO CAMPO PARA IMAGEM
    imagem_url = db.Column(db.String(200), nullable=True) # Armazena o caminho relativo da imagem
    
    # Relacionamento com itens de venda
    itens_venda = db.relationship('ItemVenda', backref='produto', lazy=True)


class PagamentoVenda(db.Model):
    """
    Modelo para registrar cada pagamento individualmente em uma venda.
    Permite múltiplos pagamentos por venda (Ex: Dinheiro + Pix).
    """
    __tablename__ = 'pagamentos_venda'
    
    id = db.Column(db.Integer, primary_key=True)
    venda_id = db.Column(db.Integer, db.ForeignKey('vendas.id'), nullable=False)
    # Coluna para a forma de pagamento (dinheiro, cartao, pix)
    forma_pagamento = db.Column(db.String(20), nullable=False) 
    valor = db.Column(db.Float, nullable=False)
    data_pagamento = db.Column(db.DateTime, default=datetime.now)


class Venda(db.Model):
    __tablename__ = 'vendas'
    
    id = db.Column(db.Integer, primary_key=True)
    numero_venda = db.Column(db.String(20), unique=True, nullable=False)
    data_venda = db.Column(db.DateTime, default=datetime.now) # Era utcnow
    # Os campos valor_total, valor_pago, troco, e forma_pagamento foram removidos 
    # ou se tornaram propriedades calculadas.
    status = db.Column(db.String(20), default='finalizada')  # 'finalizada', 'cancelada'
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    
    # Relacionamento com itens de venda
    itens = db.relationship('ItemVenda', backref='venda', lazy=True, cascade='all, delete-orphan')

    # NOVO: Relacionamento com múltiplos pagamentos
    pagamentos = db.relationship('PagamentoVenda', backref='venda', lazy=True, cascade='all, delete-orphan')

    # Propriedade dinâmica para calcular o valor total da venda
    @property
    def valor_total(self):
        # Soma todos os subtotais dos itens de venda
        return sum(item.subtotal for item in self.itens)

    # Propriedade dinâmica para calcular o valor total pago
    @property
    def valor_pago(self):
        # Soma todos os valores dos pagamentos
        return sum(pagamento.valor for pagamento in self.pagamentos)

    # Propriedade dinâmica para calcular o troco
    @property
    def troco(self):
        # O troco é a diferença entre o valor pago e o valor total
        return max(0.0, self.valor_pago - self.valor_total)

    # Propriedade para listar as formas de pagamento usadas (para exibição)
    @property
    def formas_pagamento_usadas(self):
        if not self.pagamentos:
            return "Nenhum"
        # Obtém uma lista de formas de pagamento únicas
        formas = set(p.forma_pagamento for p in self.pagamentos)
        # Formata para exibição
        return ", ".join(f.title() for f in formas)

    # Propriedade para o total em dinheiro (usado no fechamento de caixa)
    @property
    def total_dinheiro(self):
        return sum(p.valor for p in self.pagamentos if p.forma_pagamento == 'dinheiro')
    

class ItemVenda(db.Model):
    # ... (código do ItemVenda existente - sem alteração) ...
    __tablename__ = 'itens_venda'
    
    id = db.Column(db.Integer, primary_key=True)
    venda_id = db.Column(db.Integer, db.ForeignKey('vendas.id'), nullable=False)
    produto_id = db.Column(db.Integer, db.ForeignKey('produtos.id'), nullable=False)
    quantidade = db.Column(db.Integer, nullable=False)
    preco_unitario = db.Column(db.Float, nullable=False)
    subtotal = db.Column(db.Float, nullable=False)

class MovimentoCaixa(db.Model):
    # ... (código do MovimentoCaixa existente - sem alteração) ...
    __tablename__ = 'movimento_caixa'
    
    id = db.Column(db.Integer, primary_key=True)
    data_abertura = db.Column(db.DateTime, default=datetime.now) # Era utcnow
    data_fechamento = db.Column(db.DateTime)
    saldo_inicial = db.Column(db.Float, nullable=False)
    saldo_final = db.Column(db.Float)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    status = db.Column(db.String(20), default='aberto')  # 'aberto', 'fechado'
    
    # Relacionamento com usuário
    usuario = db.relationship('Usuario', backref='movimentos_caixa')