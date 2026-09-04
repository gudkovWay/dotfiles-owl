#!/usr/bin/env bash
# PreToolUse(Bash): блокирует git commit с трейлерами авторства Claude.
# Ничего не делает для любых других команд.

cmd=$(jq -r '.tool_input.command // ""')

case "$cmd" in
	*"git commit"*) ;;
	*) exit 0 ;;
esac

if printf '%s' "$cmd" | grep -qiE 'Co-Authored-By:[[:space:]]*Claude|Claude-Session:|Generated with \[?Claude Code'; then
	echo "Блокировано: в сообщении коммита трейлер авторства Claude." >&2
	echo "Глобальное правило (~/.claude/CLAUDE.md): Co-Authored-By / Claude-Session / Generated with Claude Code в коммиты не добавляются никогда." >&2
	echo "Повтори ту же команду без этих строк." >&2
	exit 2
fi

exit 0
