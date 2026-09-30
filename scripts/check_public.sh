#!/usr/bin/env bash
# Fails (non-zero) if any file in this project holds something that must not be published.
set -u
cd "$(dirname "$0")/.."
self="scripts/check_public.sh"
status=0
patterns=(
  'sk-ant-'
  'ANTHROPIC_API_KEY=[^[:space:]]'
  '/home/'
  '\.work/'
  '/grind'
  '/spec'
  '\.claude/'
  '/Users/'
  '[A-Za-z]:\\Users'
  '/mnt/[a-z]/'
  'gh[pous]_[A-Za-z0-9]{20,}'
  'github_pat_'
  '[A-Za-z0-9._%+-]+@(gmail|outlook|hotmail|yahoo)\.'
)
while IFS= read -r f; do
  [ "$f" = "$self" ] && continue
  [ -f "$f" ] || continue
  for p in "${patterns[@]}"; do
    if grep -nIE -e "$p" -- "$f" | sed "s|^|$f:|" | grep .; then status=1; fi
  done
done < <(git ls-files --cached --others --exclude-standard | sort -u)
[ "$status" -eq 0 ] && echo "check_public: clean"
exit "$status"
