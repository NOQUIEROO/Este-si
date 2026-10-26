"""Arma el cuaderno de Kaggle para entrenar PongBrain.

Uso: python3 armar_kaggle.py  →  crea la carpeta 'paquete/' con entrenamiento.ipynb y kernel-metadata.json
Después:
  kaggle kernels push -p paquete
  kaggle kernels status fabri9/pongbrain-entrenamiento
  kaggle kernels output fabri9/pongbrain-entrenamiento -p salida      (cuando diga COMPLETE)
"""
import json, os

AQUI = os.path.dirname(os.path.abspath(__file__))
ID = 'fabri9/pongbrain-entrenamiento'
ARCHIVOS = {  # nombre en Kaggle: archivo de origen
    'cultivo.js': os.path.join(AQUI, '..', 'cultivo.js'),
    'entrenar.mjs': os.path.join(AQUI, 'entrenar.mjs'),
    'corrida.sh': os.path.join(AQUI, 'corrida.sh'),
}

def celda(texto):
    return {'cell_type': 'code', 'metadata': {}, 'execution_count': None, 'outputs': [], 'source': texto.splitlines(True)}

celdas = []
for nombre, origen in ARCHIVOS.items():
    celdas.append(celda('%%writefile ' + nombre + '\n' + open(origen, encoding='utf-8').read()))
celdas.append(celda(
    '!node -v 2>/dev/null || (curl -fsSL https://nodejs.org/dist/v20.17.0/node-v20.17.0-linux-x64.tar.xz -o node.tar.xz '
    '&& mkdir -p node && tar -xf node.tar.xz -C node --strip-components=1 && ./node/bin/node -v)\n'))
celdas.append(celda('!timeout 1080 bash corrida.sh\n'))

cuaderno = {'cells': celdas, 'metadata': {'kernelspec': {'display_name': 'Python 3', 'language': 'python', 'name': 'python3'},
            'language_info': {'name': 'python'}}, 'nbformat': 4, 'nbformat_minor': 5}
salida = os.path.join(AQUI, 'paquete'); os.makedirs(salida, exist_ok=True)
json.dump(cuaderno, open(os.path.join(salida, 'entrenamiento.ipynb'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
json.dump({'id': ID, 'title': 'pongbrain-entrenamiento', 'code_file': 'entrenamiento.ipynb', 'language': 'python',
           'kernel_type': 'notebook', 'is_private': True, 'enable_internet': True, 'enable_gpu': False},
          open(os.path.join(salida, 'kernel-metadata.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print('listo:', salida)
