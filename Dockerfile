FROM python:3.13-trixie
ARG NOVNC_VERSION=1.5.0
WORKDIR /opt/proxstar
RUN apt-get update -y && apt-get install -y python3-dev libsasl2-dev git curl
COPY requirements.txt .
RUN pip install -r requirements.txt
RUN curl -fsSL https://github.com/novnc/noVNC/archive/refs/tags/v${NOVNC_VERSION}.tar.gz -o novnc.tar.gz
COPY start_worker.sh start_scheduler.sh .
COPY LICENSE.txt ./
COPY .git .git/
COPY *.py .
COPY proxstar ./proxstar
RUN mkdir -p /opt/proxstar/proxstar/static/noVNC && \ 
    tar -xzf novnc.tar.gz --strip-components=1 -C /opt/proxstar/proxstar/static/noVNC && \
    rm novnc.tar.gz
RUN touch targets && chmod a+w targets
RUN git config --system --add safe.directory '*'
ENTRYPOINT gunicorn proxstar:app --bind=0.0.0.0:8080 --config gunicorn.conf.py
