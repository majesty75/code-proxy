from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    kafka_bootstrap_servers: str = "kafka:9092"
    kafka_topic: str = "raw-logs"
    kafka_offset_reset: str = "earliest"
    ch_host: str = "clickhouse"
    ch_port: int = 8123
    ch_database: str = "uta"
    ch_username: str = "default"
    ch_password: str = "password"
    batch_size: int = 500
    flush_max_retries: int = 5
    flush_retry_max_sleep: float = 30.0
    log_level: str = "INFO"

    class Config:
        env_prefix = "UTA_"
