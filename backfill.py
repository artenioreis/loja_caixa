import sqlite3

def run():
    c = sqlite3.connect('instance/loja.db')
    try:
        c.execute("UPDATE vendas SET valor_dinheiro = valor_total WHERE forma_pagamento = 'dinheiro'")
        c.execute("UPDATE vendas SET valor_cartao = valor_total WHERE forma_pagamento = 'cartao'")
        c.execute("UPDATE vendas SET valor_pix = valor_total WHERE forma_pagamento = 'pix'")
        c.commit()
        print("Success")
    except Exception as e:
        print("Error:", e)
    finally:
        c.close()

if __name__ == '__main__':
    run()
