FROM python:3.3-slim
MAINTAINER Jeff Billimek <jeff@billimek.com>

ADD . /src
WORKDIR /src

RUN pip install -r requirements.txt

CMD ["python", "/src/InfluxdbComcast.py"]
