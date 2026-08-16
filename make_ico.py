from PIL import Image
import os

src = r'c:\CAIXA_NSG\static\images\tray_icon.png'
dst = r'c:\CAIXA_NSG\static\images\tray_icon.ico'

img = Image.open(src).convert('RGBA')
# Gera múltiplos tamanhos para o ICO
sizes = [(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)]
icons = []
for s in sizes:
    icons.append(img.resize(s, Image.LANCZOS))

icons[0].save(dst, format='ICO', sizes=sizes)
print(f'ICO gerado em: {dst}')
