from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    kafka_bootstrap_servers: str = "kafka:9092"
    kafka_topic: str = "raw-logs"
    ch_host: str = "clickhouse"
    ch_port: int = 8123
    ch_database: str = "uta"
    batch_size: int = 500
    log_level: str = "INFO"

    class Config:
        env_prefix = "UTA_"
