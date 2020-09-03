FROM ubuntu:20.04

ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y \
    python3 python3-pip \
    firefox-geckodriver \
    xvfb \
    && rm -rf /var/lib/apt/lists/*

ENV LANG C.UTF-8
ENV LC_ALL C.UTF-8
ENV PYTHONUNBUFFERED=TRUE

ENV APP_HOME /src
WORKDIR /$APP_HOME

COPY . $APP_HOME
RUN pip3 install --no-cache-dir -r requirements.txt

CMD ["python3", "-u", "$APP_HOME/InfluxdbComcast.py"]
