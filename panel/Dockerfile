FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --trusted-host pypi.org --trusted-host files.pythonhosted.org -r requirements.txt
COPY app.py .
COPY mode_defs.py .
COPY maintenance_guard.py .
COPY config_guard.py .
COPY wsgi.py .
COPY templates templates
COPY static static
EXPOSE 8080
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "--threads", "4", "--timeout", "120", "wsgi:app"]
