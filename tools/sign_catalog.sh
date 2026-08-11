#!/bin/sh

set -eu
set -f
umask 077

if [ "$#" -ne 3 ]; then
    echo "Usage: sign_catalog.sh <private-key.pem> <index.json> <signature-output>" >&2
    exit 64
fi

private_key=$1
index=$2
output=$3
signature=$(mktemp)
trap 'rm -f "$signature"' EXIT HUP INT TERM

openssl pkeyutl -sign -rawin -inkey "$private_key" -in "$index" -out "$signature"
openssl base64 -A -in "$signature" -out "$output"
printf '\n' >> "$output"
