from database import db
from flask_login import UserMixin
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

class Usuario(db.Model, UserMixin):
    # ... (código do Usuário existente - sem alteração) ...
    __tablename__ = 'usuarios'
    
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    senha_hash = db.Column(db.String(200), nullable=False)
    perfil = db.Column(db.String(20), nullable=False)  # 'admin' ou 'caixa'
    ativo = db.Column(db.Boolean, default=True)
    data_criacao = db.Column(db.DateTime, default=datetime.utcnow)
    
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
    data_criacao = db.Column(db.DateTime, default=datetime.utcnow)
    data_atualizacao = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # NOVO CAMPO PARA IMAGEM
    imagem_url = db.Column(db.String(200), nullable=True) # Armazena o caminho relativo da imagem
    
    # Relacionamento com itens de venda
    itens_venda = db.relationship('ItemVenda', backref='produto', lazy=True)

class Venda(db.Model):
    # ... (código da Venda existente - sem alteração) ...
    __tablename__ = 'vendas'
    
    id = db.Column(db.Integer, primary_key=True)
    numero_venda = db.Column(db.String(20), unique=True, nullable=False)
    data_venda = db.Column(db.DateTime, default=datetime.utcnow)
    valor_total = db.Column(db.Float, nullable=False)
    valor_pago = db.Column(db.Float, nullable=False)
    troco = db.Column(db.Float, nullable=False)
    forma_pagamento = db.Column(db.String(20), nullable=False)  # 'dinheiro', 'cartao', 'pix'
    status = db.Column(db.String(20), default='finalizada')  # 'finalizada', 'cancelada'
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    
    # Relacionamento com itens de venda
    itens = db.relationship('ItemVenda', backref='venda', lazy=True, cascade='all, delete-orphan')

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
    data_abertura = db.Column(db.DateTime, default=datetime.utcnow)
    data_fechamento = db.Column(db.DateTime)
    saldo_inicial = db.Column(db.Float, nullable=False)
    saldo_final = db.Column(db.Float)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    status = db.Column(db.String(20), default='aberto')  # 'aberto', 'fechado'
    
    # Relacionamento com usuário
    usuario = db.relationship('Usuario', backref='movimentos_caixa')