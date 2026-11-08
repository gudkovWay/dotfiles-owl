# AyuGram (ayugram-desktop-bin) собран против protobuf 36.0, в системе 36.1.
# Симлинк в ~/.local/lib даёт нужный soname. Удалить, когда -bin пересоберут.
if not contains /home/q/.local/lib $LD_LIBRARY_PATH
    set -gx LD_LIBRARY_PATH /home/q/.local/lib $LD_LIBRARY_PATH
end
