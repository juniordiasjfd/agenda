#!/usr/bin/env bash
# Build do Render (buildCommand: ./build.sh). Para no primeiro erro: um
# collectstatic ou migrate que falha cancela o deploy e a versão anterior
# continua no ar.
set -o errexit
set -o pipefail
set -o nounset

pip install --upgrade pip
pip install -r requirements.txt

python manage.py collectstatic --noinput
python manage.py migrate --noinput
