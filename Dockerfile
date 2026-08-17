FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Los dos bots del repo viven en la misma imagen y se levantan con distinto
# comando: `python main.py` (Red de Anomalias) y `python odd_main.py` (ODD).
COPY glitchmap ./glitchmap
COPY odd ./odd
COPY main.py odd_main.py ./

# La base vive en un volumen, nunca en la capa de la imagen: un redeploy
# reemplaza el codigo y no toca los datos.
ENV DATA_DIR=/data
VOLUME ["/data"]

CMD ["python", "-u", "main.py"]
