from app import app, db
from models import Venda

with app.app_context():
    vendas = Venda.query.order_by(Venda.id.desc()).limit(5).all()
    for v in vendas:
        print(f"ID:{v.id} Venda:{v.numero_venda} Total:{v.valor_total} Pago:{v.valor_pago} Dinheiro:{v.valor_dinheiro} Cartao:{v.valor_cartao} Pix:{v.valor_pix} Forma:{v.forma_pagamento}")
