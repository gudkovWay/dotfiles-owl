# Export API keys from local raw key files, if present.
# Keys live outside this repository under
# ${XDG_CONFIG_HOME:-$HOME/.config}/dotfiles-owl-private/keys/<name>.
# Missing, unreadable, or empty files leave the variable unset.

function ___export_key --argument-names key_file var
    if test -r "$key_file"; and test -s "$key_file"
        set -l value (string collect < "$key_file")
        set value (string trim --right --chars=\n -- "$value")
        if test -n "$value"
            set -gx $var "$value"
        end
    end
end

set -l keys_dir
if set -q XDG_CONFIG_HOME; and test -n "$XDG_CONFIG_HOME"
    set keys_dir "$XDG_CONFIG_HOME/dotfiles-owl-private/keys"
else
    set keys_dir "$HOME/.config/dotfiles-owl-private/keys"
end

___export_key "$keys_dir/deepseek" DEEPSEEK_API_KEY
___export_key "$keys_dir/zai" ZAI_API_KEY

functions -e ___export_key
set -e keys_dir
