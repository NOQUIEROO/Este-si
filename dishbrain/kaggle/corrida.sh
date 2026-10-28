#!/bin/bash
# 4 tareas en paralelo, una por núcleo, con tope de 17 minutos cada una
export PATH="$PWD/node/bin:$PATH"
for k in 0 1 2 3; do
  node entrenar.mjs $k 4 1000 2>&1 | tee registro_$k.txt &
done
wait
