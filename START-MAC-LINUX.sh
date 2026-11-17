#!/bin/sh
cd "$(dirname "$0")" || exit 1
if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 is not installed!"
  echo "Install it from: https://www.python.org/downloads/"
  printf "Press Enter to close..."
  read -r _
  exit 1
fi
echo "=============================="
echo "  1 = Website mode (chat page in your browser)"
echo "  2 = Text mode (type tasks here)"
echo "  3 = Voice mode (speak, fully automatic)"
echo "=============================="
printf "Choose 1, 2 or 3 and press Enter: "
read -r choice
if [ "$choice" = "2" ]; then
  python3 agent.py
elif [ "$choice" = "3" ]; then
  python3 agent.py --voice -y
else
  python3 agent.py --web
fi
