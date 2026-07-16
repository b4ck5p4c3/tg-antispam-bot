FROM ubuntu:24.04

WORKDIR /app

COPY requirements.txt /app/requirements.txt

RUN apt update \
    && apt-get install software-properties-common -y \
    && add-apt-repository ppa:deadsnakes/ppa \
    && apt-get update -y \
    && apt-get install python3.12 -y \
    && apt-get install python3-pip -y \
    && apt-get install python3.12-venv -y \
    && apt-get install tesseract-ocr-rus -y \
    && apt-get clean
RUN python3 -m venv venv \
    && ./venv/bin/python -m pip install -r requirements.txt

COPY main.py /app/main.py
COPY src /app/src
COPY data/locale /app/locales

RUN mkdir -p /app/data

ENV LOCALE_FOLDER_PATH=/app/locales

ENTRYPOINT ["venv/bin/python3.12", "main.py"]
