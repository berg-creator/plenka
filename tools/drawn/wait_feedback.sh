#!/bin/zsh
# Ждёт решения владельца по черновику: строки ok/comment в reels/<id>/feedback.jsonl
# приватного хранилища (пишет дежурство, src/reels.py note). $1 — id, $2 — строк уже было.
id=$1; base=${2:-0}
get() { gh api -H "Accept: application/vnd.github.raw" repos/berg-creator/plenka-state/contents/reels/$id/feedback.jsonl 2>/dev/null; }
while true; do
  body=$(get) || body=""
  new=$(print -r -- "$body" | grep '^{' | tail -n +$((base+1)))
  if print -r -- "$new" | grep -q '"kind": "\(ok\|comment\)"'; then
    sleep 120  # правку пишут и вторым сообщением — даём договорить
    get | grep '^{' | tail -n +$((base+1)); exit 0
  fi
  sleep 60
done
