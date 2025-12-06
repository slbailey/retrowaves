#!/bin/bash
# Start script for Tower and Station services

echo "Starting Retrowaves services..."

sudo systemctl start retrowaves-tower
sudo systemctl start retrowaves-station

echo "All services started."
