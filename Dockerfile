FROM python:3.9-slim-bullseye

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN python -m pip install -r requirements.txt

WORKDIR /
COPY . /

EXPOSE 5002

ENTRYPOINT ["gunicorn", "--config", "gunicorn_config.py", "--log-level", "info", "--access-logfile", "-", "--error-logfile", "-", "wsgi:app"]   
