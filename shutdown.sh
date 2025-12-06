#!/bin/bash
# Shutdown script for Tower and Station services

echo "Shutting down Retrowaves services..."

sudo systemctl stop retrowaves-station
sudo systemctl stop retrowaves-tower

echo "All services stopped."
