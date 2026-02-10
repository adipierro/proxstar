FROM python:3.13-trixie
ARG NOVNC_VERSION=1.5.0
WORKDIR /opt/proxstar
RUN apt-get update -y && apt-get install -y python3-dev libldap2-dev libsasl2-dev ldap-utils git curl
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY start_worker.sh start_scheduler.sh .
COPY .git .git/
COPY *.py .
COPY proxstar ./proxstar
RUN mkdir -p /opt/proxstar/proxstar/static/noVNC \
    && curl -fsSL https://github.com/novnc/noVNC/archive/refs/tags/v${NOVNC_VERSION}.tar.gz \
    | tar -xz --strip-components=1 -C /opt/proxstar/proxstar/static/noVNC
RUN touch targets && chmod a+w targets # This is some OKD shit.
RUN git config --system --add safe.directory '*' # This is also some OKD shit.
ENTRYPOINT gunicorn proxstar:app --bind=0.0.0.0:8080 --config gunicorn.conf.py
