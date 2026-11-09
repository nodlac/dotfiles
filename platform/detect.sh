# POSIX-compatible detection; safe to source from bash or zsh.
# Arguments provide fixture inputs for tests; production callers pass none.
detect_platform() {
    DF_OS= DF_DISTRO= DF_WSL=none
    df_kernel=${1:-$(uname -s)}
    df_release=${2:-$(uname -r)}
    df_os_release=${3:-/etc/os-release}
    case "$df_kernel" in
        Darwin) DF_OS=macos; DF_DISTRO=macos ;;
        Linux)
            DF_OS=linux; DF_DISTRO=unknown
            # Parse data, never execute os-release as shell code.
            if [ -r "$df_os_release" ]; then
                while IFS='=' read -r df_key df_value; do
                    case "$df_key" in
                        ID) DF_DISTRO=$(printf '%s' "$df_value" | tr -d '\042\047') ;;
                    esac
                done < "$df_os_release"
            fi
            case "$df_release" in
                *[Mm]icrosoft*|*[Ww][Ss][Ll]*)
                    case "$df_release" in
                        *[Ss]tandard*|*[Ww][Ss][Ll]2*) DF_WSL=2 ;;
                        *) DF_WSL=1 ;;
                    esac ;;
            esac ;;
        *) printf 'Unsupported operating system: %s\n' "$df_kernel" >&2; return 1 ;;
    esac
}
