import os
from app import app, db
from models import MovimentoEstoque

def create_table():
    with app.app_context():
        # Using db.engine to emit the create table command only for this model
        MovimentoEstoque.__table__.create(db.engine, checkfirst=True)
        print("Tabela movimento_estoque criada com sucesso (se não existia).")

if __name__ == '__main__':
    create_table()
