FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY service_importer/requirements.txt /app/service_importer/requirements.txt
COPY provider_assignment/requirements.txt /app/provider_assignment/requirements.txt
COPY booking_bridge/requirements.txt /app/booking_bridge/requirements.txt
COPY booking_bridge/requirements.lock.txt /app/booking_bridge/requirements.lock.txt
RUN pip install --no-cache-dir -r booking_bridge/requirements.lock.txt
COPY service_importer/*.py /app/service_importer/
COPY provider_assignment/*.py /app/provider_assignment/
COPY booking_bridge /app/booking_bridge
RUN useradd --uid 10001 --create-home bridge && mkdir -p /state /app/provider_assignment/state && chown -R bridge:bridge /state /app/provider_assignment/state
USER 10001:10001
CMD ["python", "-m", "uvicorn", "booking_bridge.api:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--workers", "1"]
