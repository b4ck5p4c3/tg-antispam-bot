FROM ubuntu:24.04

WORKDIR /app

COPY . /app

RUN apt update \
    && apt-get install software-properties-common -y \
    && add-apt-repository ppa:deadsnakes/ppa \
    && apt-get update -y \
    && apt-get install python3.12 -y \
    && apt-get install python3-pip -y \
    && apt-get install python3.12-venv -y \
    && apt-get clean
RUN python3 -m venv venv \
    && ./venv/bin/python -m pip install -r requirements.txt

CMD ["venv/bin/python3.12", "main.py"]