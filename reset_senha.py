import sqlite3
from werkzeug.security import generate_password_hash

db_path = r'c:\CAIXA_NSG\instance\loja.db'
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

nova_senha = 'admin123'
novo_hash = generate_password_hash(nova_senha)

cursor.execute("UPDATE usuarios SET senha_hash = ? WHERE email = ?", (novo_hash, 'admin@loja.com'))
conn.commit()

# Confirmar
cursor.execute("SELECT id, nome, email, perfil FROM usuarios WHERE email = 'admin@loja.com'")
row = cursor.fetchone()
print(f"Senha redefinida com sucesso!")
print(f"ID: {row[0]} | Nome: {row[1]} | Email: {row[2]} | Perfil: {row[3]}")
print(f"\nUse para login:")
print(f"  Email: admin@loja.com")
print(f"  Senha: admin123")

conn.close()
