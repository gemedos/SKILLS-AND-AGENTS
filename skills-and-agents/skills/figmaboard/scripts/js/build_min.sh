#!/bin/sh
# Maintainer step: regenerate figma_runtime.min.js after editing figma_runtime.js (needs: npm i -g terser).
# The skill itself never needs Node; build_push.py/build_pull.py use the .min.js when it is up to date.
cd "$(dirname "$0")"
{ echo 'async function __fb(P){'; cat figma_runtime.js; echo '}'; } > /tmp/__fb_wrapped.js
terser /tmp/__fb_wrapped.js -c passes=2 -m -o figma_runtime.min.js && rm /tmp/__fb_wrapped.js
sha1sum figma_runtime.js | cut -c1-12 > figma_runtime.min.sha
