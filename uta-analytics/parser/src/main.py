from consumer import LogConsumer
from config import Settings


def main():
    settings = Settings()
    consumer = LogConsumer(settings)
    consumer.run()


if __name__ == "__main__":
    main()
