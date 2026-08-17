#!/usr/bin/env python3
"""Punto de entrada del bot de ODD: python odd_main.py

El otro bot del repo (la Red de Anomalías) arranca con `python main.py`. Son
dos procesos distintos, con dos tokens y dos bases distintas.
"""

from odd.app import main

if __name__ == "__main__":
    main()
