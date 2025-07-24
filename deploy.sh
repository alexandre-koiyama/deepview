#!/bin/bash
cd /home/ec2-user/deepview
git pull origin main
source venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart deepview
echo "Deployment completed successfully."