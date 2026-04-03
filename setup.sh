#!/bin/bash
export DEBIAN_FRONTEND=noninteractive
sudo apt-get update
sudo apt-get install ffmpeg jq nodejs npm curl -y

# Setup WARP repo
curl -fsSL https://pkg.cloudflareclient.com/pubkey.gpg | sudo gpg --yes --dearmor --output /usr/share/keyrings/cloudflare-warp-archive-keyring.gpg
echo "deb [signed-by=/usr/share/keyrings/cloudflare-warp-archive-keyring.gpg] https://pkg.cloudflareclient.com/ $(lsb_release -cs) main" | sudo tee /etc/apt/sources.list.d/cloudflare-client.list

sudo apt-get update
sudo apt-get install cloudflare-warp -y

warp-cli --accept-tos register
warp-cli --accept-tos set-mode proxy
warp-cli --accept-tos set-proxy-port 40000
warp-cli --accept-tos connect

curl -LsSf https://astral.sh/uv/install.sh | sh

sudo ufw allow 8000/tcp

cd /home/ubuntu/VideoSnap
export PATH="$HOME/.local/bin:$PATH"
uv sync

if [ -f ig_node_module/package.json ]; then
    cd ig_node_module && npm install && cd ..
fi
