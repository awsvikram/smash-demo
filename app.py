import uuid
import time
import logging
import json
import os
from flask import Flask, request, jsonify
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST

app = Flask(__name__)

# --- Structured JSON logger ---
class JsonFormatter(logging.Formatter):
    def format(self, record):
        log = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "message": record.getMessage(),
            "service": os.getenv("SERVICE_NAME", "sample-app"),
            "version": os.getenv("SERVICE_VERSION", "1.0.0"),
        }
        # Merge any extra fields (trace_id, message_id, etc.)
        for key in ("trace_id", "message_id", "status_code", "duration_ms", "path"):
            if hasattr(record, key):
                log[key] = getattr(record, key)
        return json.dumps(log)

handler = logging.StreamHandler()
handler.setFormatter(JsonFormatter())
logger = logging.getLogger("sample-app")
logger.setLevel(logging.INFO)
logger.addHandler(handler)
logger.propagate = False

# --- Prometheus metrics ---
REQUEST_COUNT = Counter(
    "app_requests_total",
    "Total HTTP requests",
    ["method", "path", "status_code"]
)

REQUEST_LATENCY = Histogram(
    "app_request_duration_seconds",
    "HTTP request latency",
    ["method", "path"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5]
)

ACTIVE_REQUESTS = Gauge(
    "app_active_requests",
    "Currently active requests"
)

MESSAGES_PROCESSED = Counter(
    "app_messages_processed_total",
    "Total messages processed",
    ["message_type", "trace_id"]
)

# --- Routes ---
@app.before_request
def before_request():
    request.start_time = time.time()
    # Propagate or generate trace_id from incoming header
    request.trace_id = request.headers.get("X-Trace-Id", str(uuid.uuid4()))
    request.message_id = request.headers.get("X-Message-Id", str(uuid.uuid4()))
    ACTIVE_REQUESTS.inc()

@app.after_request
def after_request(response):
    duration = time.time() - request.start_time
    duration_ms = round(duration * 1000, 2)

    REQUEST_COUNT.labels(
        method=request.method,
        path=request.path,
        status_code=response.status_code
    ).inc()

    REQUEST_LATENCY.labels(
        method=request.method,
        path=request.path
    ).observe(duration)

    ACTIVE_REQUESTS.dec()

    logger.info(
        f"{request.method} {request.path} {response.status_code}",
        extra={
            "trace_id": request.trace_id,
            "message_id": request.message_id,
            "status_code": response.status_code,
            "duration_ms": duration_ms,
            "path": request.path,
        }
    )
    return response

@app.route("/")
def index():
    return jsonify({
        "status": "ok",
        "trace_id": request.trace_id,
        "message_id": request.message_id,
    })

@app.route("/process")
def process():
    msg_type = request.args.get("type", "default")
    # Simulate some work
    time.sleep(0.01)

    MESSAGES_PROCESSED.labels(
        message_type=msg_type,
        trace_id=request.trace_id
    ).inc()

    logger.info(
        f"Processed message type={msg_type}",
        extra={
            "trace_id": request.trace_id,
            "message_id": request.message_id,
            "path": request.path,
        }
    )
    return jsonify({
        "processed": True,
        "message_type": msg_type,
        "trace_id": request.trace_id,
        "message_id": request.message_id,
    })

@app.route("/health")
def health():
    return jsonify({"status": "healthy"})

@app.route("/metrics")
def metrics():
    return generate_latest(), 200, {"Content-Type": CONTENT_TYPE_LATEST}

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
