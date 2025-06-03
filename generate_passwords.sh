#!/bin/bash

# Generate passwords using pwgen
CUSTOM_PASSWORD=$(pwgen -s 16 1)
BASIC_PASSWORD=$(pwgen -s 16 1)
PLAYER_PASSWORD=$(pwgen -s 16 1)
MODERATOR_PASSWORD=$(pwgen -s 16 1)
ADMIN_PASSWORD=$(pwgen -s 16 1)

# Update .env file
sed -i "s/^TELEGRAM_TOKEN=.*/TELEGRAM_TOKEN=${TELEGRAM_TOKEN}/" example.env
sed -i "s/^CUSTOM_PASSWORD=.*/CUSTOM_PASSWORD=${CUSTOM_PASSWORD}/" example.env
sed -i "s/^BASIC_PASSWORD=.*/BASIC_PASSWORD=${BASIC_PASSWORD}/" example.env
sed -i "s/^PLAYER_PASSWORD=.*/PLAYER_PASSWORD=${PLAYER_PASSWORD}/" example.env
sed -i "s/^MODERATOR_PASSWORD=.*/MODERATOR_PASSWORD=${MODERATOR_PASSWORD}/" example.env
sed -i "s/^ADMIN_PASSWORD=.*/ADMIN_PASSWORD=${ADMIN_PASSWORD}/" example.env
sed -i "s/^WORLD_NAME=.*/WORLD_NAME=\"${WORLD_NAME}\"/" example.env

echo "Passwords generated and updated in example.env"
