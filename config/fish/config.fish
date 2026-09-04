source /usr/share/cachyos-fish-config/cachyos-config.fish

# overwrite greeting
# potentially disabling fastfetch
#function fish_greeting
#    # smth smth
#end

# --- abbreviations ---
# разворачиваются прямо в строке при пробеле/enter, так что можно дописать аргументы
if status is-interactive
    abbr -a c    claude
    abbr -a lzg  lazygit
    abbr -a lzd  lazydocker

    abbr -a nrd   'npm run dev -w'
    abbr -a nrdpa 'npm run dev -w payscrow-admin'
    abbr -a nrdpm 'npm run dev -w payscrow-merchant'
    abbr -a nrdpp 'npm run dev -w payscrow-provider'

    abbr -a ga  'git add .'
    abbr -a gc  --set-cursor -- 'git commit -m "%"'
    abbr -a gpd 'git push origin dev'
    abbr -a gp  'git push origin'
    abbr -a gcl 'git clone git@github.com:'
    abbr -a n 'nvim'
    abbr -a l 'ls -la'
end

# --- локальный ИИ: кэши на 3-й NVMe, чтобы не забивать корневой диск ---
set -gx HF_HOME /home/q/storage/ai/cache/hf
set -gx TORCH_HOME /home/q/storage/ai/cache/torch
