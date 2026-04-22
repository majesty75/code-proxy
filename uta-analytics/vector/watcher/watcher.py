import os
import json
import time
import socket
import logging
from pathlib import Path
from watchdog.observers import Observer
from watchdog.observers.polling import PollingObserver
from watchdog.events import FileSystemEventHandler
from kafka import KafkaProducer

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load configurations from environment or use defaults
WATCH_DIR = os.environ.get("WATCH_DIR", "/uta/UTA_FULL_Logs")
KAFKA_BROKER = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
TOPIC = os.environ.get("KAFKA_TOPIC", "raw-logs")
SERVER_IP = os.environ.get("VECTOR_SERVER_IP", socket.gethostbyname(socket.gethostname()))

# USE_POLLING defaults to true because it is more reliable on Docker bind mounts (Mac/Windows)
USE_POLLING = os.environ.get("USE_POLLING", "true").lower() == "true"

class LogMovedHandler(FileSystemEventHandler):
    def __init__(self, producer):
        self.producer = producer

    def _handle_event(self, filepath):
        # Convert to string and handle path
        path_str = str(filepath)
        if not path_str.endswith(".log"):
            return
            
        filename = os.path.basename(path_str)
        logger.info(f"Detected change/move for {filename}. Sending completion event.")
        
        payload = {
            "system_event": "test_completed",
            "filename": filename,
            "server_ip": SERVER_IP,
            "timestamp": time.time()
        }
        
        try:
            self.producer.send(TOPIC, json.dumps(payload).encode("utf-8"))
            self.producer.flush()
        except Exception as e:
            logger.error(f"Failed to send Kafka message for {filename}: {e}")

    def on_moved(self, event):
        # When a file is moved, we care about the source path (the one that disappeared from the watched area)
        # or the destination path if it moved into a watched area.
        # For UTA, moving to 'completed' triggers the completion.
        self._handle_event(event.src_path)

    def on_deleted(self, event):
        self._handle_event(event.src_path)

def main():
    logger.info(f"Watcher starting. Polling: {USE_POLLING}, Dir: {WATCH_DIR}")
    logger.info(f"Connecting to Kafka broker at {KAFKA_BROKER}...")
    
    producer = None
    while not producer:
        try:
            producer = KafkaProducer(bootstrap_servers=KAFKA_BROKER)
            logger.info("Connected to Kafka!")
        except Exception as e:
            logger.warning(f"Waiting for Kafka... {e}")
            time.sleep(5)

    # Ensure watch directory exists
    Path(WATCH_DIR).mkdir(parents=True, exist_ok=True)
    
    event_handler = LogMovedHandler(producer)
    
    # Choose observer type based on environment
    observer = PollingObserver() if USE_POLLING else Observer()
    observer.schedule(event_handler, WATCH_DIR, recursive=True)
    
    logger.info(f"Starting observer on {WATCH_DIR}...")
    observer.start()
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        observer.stop()
    observer.join()

if __name__ == "__main__":
    main()
