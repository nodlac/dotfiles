# Server-specific zsh config — sourced when MACHINE_ENV=server (see ~/.zshrc)

# Serve the current directory over HTTP: serve [port]
serve() { python3 -m http.server "${1:-8000}"; }

# Follow a systemd unit's logs: jlog <unit>
jlog() { journalctl -fu "$1"; }

# apt upgrade shorthand
sysupdate() { sudo apt-get update && sudo apt-get upgrade; }
