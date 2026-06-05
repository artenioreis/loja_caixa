import sqlite3

# Verificar o banco principal em uso
db_path = r'c:\CAIXA_NSG\instance\loja.db'

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Listar tabelas
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [t[0] for t in cursor.fetchall()]
print("Tabelas:", tables)

# Buscar tabela de usuários
for tname in tables:
    if any(x in tname.lower() for x in ['user', 'usu', 'login', 'admin', 'func']):
        print(f"\n=== Tabela: {tname} ===")
        cursor.execute(f"PRAGMA table_info({tname})")
        cols = [c[1] for c in cursor.fetchall()]
        print("Colunas:", cols)
        cursor.execute(f"SELECT * FROM {tname}")
        for row in cursor.fetchall():
            print(row)

conn.close()
