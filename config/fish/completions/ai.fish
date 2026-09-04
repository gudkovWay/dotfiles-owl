# дополнения для bin/ai (истории и индексы локального агента)
set -l cmds hist new runs sess last resume day days grep note triage ask recall idx stores build help

complete -c ai -f
complete -c ai -n "not __fish_seen_subcommand_from $cmds" -a hist   -d "прогоны и сессии вперемешку"
complete -c ai -n "not __fish_seen_subcommand_from $cmds" -a new    -d "только не открытое"
complete -c ai -n "not __fish_seen_subcommand_from $cmds" -a runs   -d "прогоны Qwen"
complete -c ai -n "not __fish_seen_subcommand_from $cmds" -a sess   -d "сессии Claude"
complete -c ai -n "not __fish_seen_subcommand_from $cmds" -a last   -d "последняя запись в редакторе"
complete -c ai -n "not __fish_seen_subcommand_from $cmds" -a resume -d "продолжить сессию Claude"
complete -c ai -n "not __fish_seen_subcommand_from $cmds" -a day    -d "дневник за день"
complete -c ai -n "not __fish_seen_subcommand_from $cmds" -a days   -d "листать дневник"
complete -c ai -n "not __fish_seen_subcommand_from $cmds" -a grep   -d "поиск по телу историй"
complete -c ai -n "not __fish_seen_subcommand_from $cmds" -a note   -d "заметка к прогону"
complete -c ai -n "not __fish_seen_subcommand_from $cmds" -a ask    -d "спросить индекс проекта"
complete -c ai -n "not __fish_seen_subcommand_from $cmds" -a recall -d "спросить свои сессии"
complete -c ai -n "not __fish_seen_subcommand_from $cmds" -a idx    -d "листать куски индекса"
complete -c ai -n "not __fish_seen_subcommand_from $cmds" -a stores -d "какие есть индексы"
complete -c ai -n "not __fish_seen_subcommand_from $cmds" -a triage  -d "разбор: что класть в индекс"
complete -c ai -n "not __fish_seen_subcommand_from $cmds" -a build  -d "пересобрать истории"

complete -c ai -n "__fish_seen_subcommand_from triage" \
  -a "pass review warn guard run escalate list set scan state" -d "что делать с разбором"

# имена сторов там, где они уместны
complete -c ai -n "__fish_seen_subcommand_from idx" \
  -a "(command ls /home/q/storage/ai/index/stores 2>/dev/null)"
complete -c ai -n "__fish_seen_subcommand_from ask" -l store \
  -a "(command ls /home/q/storage/ai/index/stores 2>/dev/null)" -d "какой индекс спрашивать"

# даты дневника
complete -c ai -n "__fish_seen_subcommand_from day" \
  -a "(command ls /home/q/storage/ai/journal 2>/dev/null | string replace -r '\\.md\$' '' | string match -r '^\\d{4}-')"

# имена прогонов для заметок
complete -c ai -n "__fish_seen_subcommand_from note" \
  -a "(command ls /home/q/storage/ai/runs 2>/dev/null)"
