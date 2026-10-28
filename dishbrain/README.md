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

## PongBrain en 3D (`pongbrain/`)

El aparato diseñado en Blender, animado en el navegador con el mismo motor
(`engine.js`). La pantalla de vidrio se desliza hacia arriba y la botonera
SUBE/BAJA hacia la izquierda, para ver las neuronas que sienten la pelota y las
que manejan los botones. El grosor de los filamentos que van de las neuronas
sensoriales a las motoras sigue la fuerza de esas conexiones en el modelo.

- `pongbrain.gltf.json`: el aparato exportado de Blender (glTF con los datos embebidos).
- `filamentos.json`: las trayectorias de los filamentos sobre la placa.

Servilo desde la carpeta `dishbrain/` (`python3 -m http.server`) y abrí
`/pongbrain/`.
