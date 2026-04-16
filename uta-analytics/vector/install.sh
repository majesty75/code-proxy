#!/bin/bash
curl --proto '=https' --tlsv1.2 -sSfL https://sh.vector.dev | bash
# Copy config
sudo cp vector.toml /etc/vector/vector.toml
# Set environment
echo 'VECTOR_SERVER_IP=192.168.1.10' | sudo tee /etc/default/vector
echo 'KAFKA_BOOTSTRAP_SERVERS=192.168.1.100:9092' | sudo tee -a /etc/default/vector
# Enable service
sudo systemctl enable --now vector
