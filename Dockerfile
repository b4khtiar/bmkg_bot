FROM python:3.11-alpine

RUN apk add --no-cache tzdata

WORKDIR /app

# BMKG timestamps are WIB. Without this the container runs UTC and anything
# comparing datetime.now() to BMKG local_datetime is off by hours.
ENV TZ=Asia/Jakarta

RUN pip install --upgrade pip
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/

EXPOSE 8080

CMD ["python", "src/main.py"]
