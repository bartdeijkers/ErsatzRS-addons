#!/bin/sh
set -eu
case "$0" in */*) script_dir=${0%/*} ;; *) script_dir=. ;; esac
exec node "$script_dir/libexec/pages.mts" "${1:-}"
