#!/bin/bash
# 4 tareas en paralelo, una por núcleo, con tope de 17 minutos cada una
export PATH="$PWD/node/bin:$PATH"
for k in 0 1 2 3; do
  node entrenar.mjs $k 4 1020 > registro_$k.txt 2>&1 &
done
wait
cat registro_*.txt
