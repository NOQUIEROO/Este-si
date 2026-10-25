# DishBrain en tu navegador

Simulación del experimento de Cortical Labs (Kagan et al., *Neuron* 2022) en el
que neuronas cultivadas sobre una matriz de electrodos aprendieron a jugar Pong.

Abrí `index.html` en un navegador (mejor servido por HTTP para que el
experimento completo use workers):

```bash
cd dishbrain && python3 -m http.server 8000   # y entrá a http://localhost:8000
```

- `engine.js`: el modelo. 96 neuronas sensoriales (8 electrodos) y 80 motoras
  (4 regiones), neuronas de Izhikevich, STDP con trazas de elegibilidad. El
  estímulo predecible (golpe) consolida los cambios recientes; el impredecible
  (fallo) los revierte y sacude las conexiones. Funciona también en Node:
  `const DishBrain = require('./engine.js')`.
- `worker.js`: corre el experimento completo (4 condiciones × 3 cultivos × 20 min).
- `index.html`: el juego, la vista del plato, el ráster, lo que aprendió cada
  electrodo y la curva de aprendizaje.

Resultado típico del experimento completo: solo la condición **Estímulo**
mejora (≈0,3 → 1,4 golpes por rally); Silencio, Sin feedback y Reposo quedan
planas. La regla de aprendizaje es una hipótesis del modelo, no un mecanismo
medido en el paper.
