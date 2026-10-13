FROM python:3.11-slim
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 5002
# --preload: create tables and seed once in the master process, not in every worker at the same time
CMD ["gunicorn", "--preload", "-w", "2", "-b", "0.0.0.0:5002", "wsgi:app"]
