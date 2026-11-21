#!/bin/sh
# Все тесты проекта, локально и без сети: данные каталога + Worker nastolki-api на моке KV.
set -e
ROOT=$(dirname "$0")
python3 -m unittest discover -s "$ROOT/tests"
node --test "$ROOT/worker/test/index.test.mjs"
