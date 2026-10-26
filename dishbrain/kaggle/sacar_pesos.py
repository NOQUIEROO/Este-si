# Lee el registro de Kaggle (kaggle kernels logs ... > log.txt) y guarda el mejor cultivo entrenado para el aparato.
import json, sys
L = json.load(open(sys.argv[1]))
out = ''.join(x['data'] for x in L if x['stream_name'] == 'stdout')
best = None
for l in out.splitlines():
    if l.startswith('PESOS '):
        r = json.loads(l[6:])
        if not best or r['final'] > best['final']: best = r
if not best: sys.exit('no hay pesos en el registro')
keep = {k: best[k] for k in ('v', 'seed', 'curva', 'final', 'W')}
keep['params'] = {k: v for k, v in best['v'].items() if k != 'control'}
json.dump(keep, open(sys.argv[2], 'w'))
print('mejor', best['v'], 'semilla', best['seed'], 'curva', best['curva'])
