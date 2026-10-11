FROM python:3.12-slim-bookworm
WORKDIR /app
COPY panel/ /app/panel/
COPY runtime/ /app/runtime/
ENV PYTHONUNBUFFERED=1
EXPOSE 8080
CMD ["python", "-m", "panel.server"]
