FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY glitchmap ./glitchmap
COPY main.py ./

# La base vive en un volumen, nunca en la capa de la imagen: un redeploy
# reemplaza el codigo y no toca los datos.
ENV DATA_DIR=/data
VOLUME ["/data"]

CMD ["python", "-u", "main.py"]
