# PongBrain: ¿aprende el cultivo? (pruebas del 27/10)

Medida: golpes por rally en los minutos 0–5 (T1) y 5–20 (T2), como en el paper (Kagan et al. 2022).
Cada grupo: 16 cultivos distintos (semillas 101–116), 1.200 células, STDP lento (0,005) con ventana de 20 ms.

| diseño | grupo | T1 | T2 | cambio medio | mejoraron |
|---|---|---|---|---|---|
| entrada por la fila del paper | con premio y castigo | 2,31 | 2,68 | +0,37 ± 0,31 | 11 de 16 |
| entrada por la fila del paper | sin feedback | 2,88 | 2,58 | −0,30 ± 0,24 | 4 de 16 |
| espejo (cada célula lee lo que tiene encima) | con premio y castigo | 0,62 | 0,63 | +0,02 ± 0,05 | 9 de 16 |
| espejo (cada célula lee lo que tiene encima) | sin feedback | 0,58 | 0,61 | +0,04 ± 0,06 | 9 de 16 |

- Con la entrada del paper aparece el efecto del paper (mejora con feedback, empeora sin él), sin ser todavía concluyente.
- Con el espejo no hay aprendizaje: la señal de la pelota casi no llega a las células de SUBE/BAJA y,
  cuando llega, se mezcla con la de la propia paleta (que empuja la paleta contra la pared).
- 4.000 células: las conexiones de cada mitad de la cancha van al botón correcto, pero el cultivo dispara
  avalanchas al estimularlo; con inTotalE 210 se calma. Tampoco aprendió en espejo.
