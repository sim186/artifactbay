#!/bin/sh
# ArtifactBay installer — one command, from nothing to a running instance your
# agents can push to.
#
#   curl -fsSL https://raw.githubusercontent.com/sim186/artifactbay/main/install.sh | sh
#
# What it does, in order:
#   1. server  — writes ~/artifactbay/{docker-compose.deploy.yml,.env} with freshly
#                generated secrets and brings the stack up from prebuilt GHCR images.
#   2. client  — installs the stdlib-only CLI + MCP server to ~/.local/share/artifactbay,
#                puts `artifactbay` on PATH, and points it at the instance.
#   3. agents  — registers the MCP server with Claude Code if `claude` is on PATH.
#
# Only want one half?
#   ... | sh -s -- --server-only
#   ... | sh -s -- --client-only --url https://artifacts.example.com --key ab_...
#
# Re-running is safe: existing secrets are never regenerated, and an existing
# install is upgraded in place.
set -eu

REPO="sim186/artifactbay"
REF="${ARTIFACTBAY_REF:-main}"
RAW="https://raw.githubusercontent.com/${REPO}"

MODE="all"                 # all | server | client
DIR="${ARTIFACTBAY_DIR:-$HOME/artifactbay}"
LIB="${ARTIFACTBAY_LIB_DIR:-$HOME/.local/share/artifactbay}"
BIN="${ARTIFACTBAY_BIN_DIR:-$HOME/.local/bin}"
PORT="${ARTIFACTBAY_WEB_PORT:-8080}"
BASE_URL=""
URL=""
KEY=""
WITH_MCP=1
COMPOSE_FILE="docker-compose.deploy.yml"
# Explicit project name: keeps up/down/logs stable whatever the directory is
# called, and keeps this stack distinct from the `-p artifactbay-full` dev one.
PROJECT="${ARTIFACTBAY_PROJECT:-artifactbay}"

B=""; DIM=""; OK=""; ERR=""; R=""
if [ -t 1 ]; then
  B="$(printf '\033[1m')"; DIM="$(printf '\033[2m')"
  OK="$(printf '\033[32m')"; ERR="$(printf '\033[31m')"; R="$(printf '\033[0m')"
fi

say()  { printf '%s\n' "$*"; }
step() { printf '%s\n' "${B}==>${R} $*"; }
note() { printf '%s\n' "${DIM}    $*${R}"; }
good() { printf '%s\n' "  ${OK}✓${R} $*"; }
warn() { printf '%s\n' "  ${ERR}!${R} $*" >&2; }
die()  { printf '%s\n' "${ERR}✗${R} $*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

usage() {
  cat <<EOF
ArtifactBay installer

  --server-only        just run the stack (no CLI/MCP install)
  --client-only        just install the CLI + MCP server
  --dir PATH           where the stack lives            (default: $HOME/artifactbay)
  --port N             host port for the dashboard      (default: 8080)
  --base-url URL       public origin, if behind a reverse proxy
  --url URL            existing instance to point the client at (client-only)
  --key ab_...         API key for that instance        (client-only)
  --bin-dir PATH       where to link \`artifactbay\`      (default: $HOME/.local/bin)
  --ref REF            branch/tag to install from       (default: main)
  --no-mcp             skip agent MCP registration
  -h, --help           this
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --server-only|--server) MODE="server" ;;
    --client-only|--client) MODE="client" ;;
    --dir)       DIR="${2:?--dir needs a path}"; shift ;;
    --port)      PORT="${2:?--port needs a number}"; shift ;;
    --base-url)  BASE_URL="${2:?--base-url needs a URL}"; shift ;;
    --url)       URL="${2:?--url needs a URL}"; shift ;;
    --key)       KEY="${2:?--key needs a value}"; shift ;;
    --bin-dir)   BIN="${2:?--bin-dir needs a path}"; shift ;;
    --ref)       REF="${2:?--ref needs a git ref}"; shift ;;
    --no-mcp)    WITH_MCP=0 ;;
    -h|--help)   usage; exit 0 ;;
    *) die "unknown option: $1 (try --help)" ;;
  esac
  shift
done

# ── helpers ──────────────────────────────────────────────────────────────────

# Prefer the files next to this script when run from a checkout; fall back to
# raw.githubusercontent so the curl|sh path needs no clone.
SRC_DIR=""
case "${0:-}" in
  */*) _d=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd) 2>/dev/null || _d=""
       [ -n "$_d" ] && [ -f "$_d/$COMPOSE_FILE" ] && SRC_DIR="$_d" ;;
esac

fetch() {  # fetch <repo-relative-path> <dest>
  _src="$1"; _dst="$2"
  if [ -n "$SRC_DIR" ] && [ -f "$SRC_DIR/$_src" ]; then
    cp "$SRC_DIR/$_src" "$_dst"
  elif have curl; then
    curl -fsSL "$RAW/$REF/$_src" -o "$_dst" || die "download failed: $_src"
  elif have wget; then
    wget -qO "$_dst" "$RAW/$REF/$_src" || die "download failed: $_src"
  else
    die "need curl or wget"
  fi
}

rand_hex() {  # rand_hex <bytes>
  if have openssl; then
    openssl rand -hex "$1"
  elif have python3; then
    python3 -c 'import secrets,sys; print(secrets.token_hex(int(sys.argv[1])))' "$1"
  elif [ -r /dev/urandom ] && have od; then
    od -vAn -N"$1" -tx1 /dev/urandom | tr -d ' \n'; echo
  else
    die "no source of randomness (install openssl or python3)"
  fi
}

env_get() {  # env_get <file> <key> — value of KEY=… , empty if absent
  [ -f "$1" ] || return 0
  sed -n "s/^$2=//p" "$1" | tail -n1
}

port_busy() {
  if have lsof; then lsof -iTCP:"$1" -sTCP:LISTEN -n -P >/dev/null 2>&1 && return 0
  elif have ss;   then ss -ltn 2>/dev/null | grep -q "[:.]$1[[:space:]]" && return 0
  fi
  return 1
}

# ── 1. server ────────────────────────────────────────────────────────────────

install_server() {
  step "Self-hosted stack → $DIR"

  have docker || die "docker not found — install Docker, or use --client-only to point at a remote instance"
  docker compose version >/dev/null 2>&1 \
    || die "\`docker compose\` (v2) not available — update Docker, or use --client-only"
  docker info >/dev/null 2>&1 || die "cannot talk to the Docker daemon — is it running?"

  mkdir -p "$DIR"
  fetch "$COMPOSE_FILE" "$DIR/$COMPOSE_FILE"
  good "compose file"

  ENV_FILE="$DIR/.env"
  if [ -f "$ENV_FILE" ]; then
    good "keeping existing .env (secrets untouched)"
    PORT="$(env_get "$ENV_FILE" ARTIFACTBAY_WEB_PORT || true)"; PORT="${PORT:-8080}"
    KEY="$(env_get "$ENV_FILE" ARTIFACTBAY_API_KEY || true)"
    BASE_URL="$(env_get "$ENV_FILE" ARTIFACTBAY_BASE_URL || true)"
    ADMIN_PW=""
  else
    [ -n "$BASE_URL" ] || BASE_URL="http://localhost:$PORT"
    KEY="ab_$(rand_hex 24)"
    ADMIN_PW="$(rand_hex 12)"
    JWT="$(rand_hex 48)"
    PG_PW="$(rand_hex 24)"
    case "$BASE_URL" in https://*) SECURE=true ;; *) SECURE=false ;; esac

    ( umask 077; cat > "$ENV_FILE" <<EOF
# Generated by install.sh on $(date -u '+%Y-%m-%dT%H:%M:%SZ'). Keep it out of git.
ARTIFACTBAY_BASE_URL=$BASE_URL
ARTIFACTBAY_API_KEY=$KEY
ARTIFACTBAY_JWT_SECRET=$JWT
ARTIFACTBAY_ADMIN_USERNAME=admin
ARTIFACTBAY_ADMIN_PASSWORD=$ADMIN_PW
POSTGRES_PASSWORD=$PG_PW
ARTIFACTBAY_WEB_PORT=$PORT
ARTIFACTBAY_COOKIE_SECURE=$SECURE
# ARTIFACTBAY_IMAGE_TAG=latest   # pin a release, e.g. v1.0.0
EOF
    )
    good "generated secrets → $ENV_FILE (chmod 600)"
  fi

  if port_busy "$PORT"; then
    warn "port $PORT is already in use — if this isn't ArtifactBay, re-run with --port N"
  fi

  step "Pulling images and starting (first run downloads ~a few hundred MB)"
  ( cd "$DIR" && docker compose -p "$PROJECT" -f "$COMPOSE_FILE" up -d --pull always ) \
    || die "docker compose up failed — logs: (cd $DIR && docker compose -p $PROJECT -f $COMPOSE_FILE logs)"

  URL="${URL:-http://localhost:$PORT}"
  printf '    waiting for health'
  i=0
  while [ "$i" -lt 90 ]; do
    if have curl && curl -fsS "http://localhost:$PORT/health" >/dev/null 2>&1; then break; fi
    if ! have curl && have wget && wget -qO- "http://localhost:$PORT/health" >/dev/null 2>&1; then break; fi
    printf '.'; sleep 2; i=$((i + 1))
  done
  printf '\n'
  if [ "$i" -ge 90 ]; then
    warn "not healthy yet — check (cd $DIR && docker compose -p $PROJECT -f $COMPOSE_FILE logs -f)"
  else
    good "up at ${B}http://localhost:$PORT${R}"
  fi

  [ -n "$ADMIN_PW" ] && { note "admin login: admin / $ADMIN_PW"; note "(also in $ENV_FILE)"; }
  return 0
}

# ── 2. client (CLI + MCP) ────────────────────────────────────────────────────

try_init() {  # try_init <url> — writes config only if the key checks out there
  python3 "$LIB/artifactbay_cli.py" init --url "$1" --key "$KEY" >/dev/null 2>&1
}

install_client() {
  step "Agent client → $LIB"

  have python3 || die "python3 not found — the CLI and MCP server need it (stdlib only, no pip)"

  mkdir -p "$LIB" "$BIN"
  for f in artifactbay_core.py artifactbay_cli.py artifactbay_mcp.py; do
    fetch "integrations/$f" "$LIB/$f"
  done
  # Absolute path, not $(dirname $0): the launcher is reached through a symlink
  # on PATH, and dirname would resolve to the link's directory, not the library.
  cat > "$LIB/artifactbay" <<EOF
#!/bin/sh
exec python3 "$LIB/artifactbay_cli.py" "\$@"
EOF
  chmod +x "$LIB/artifactbay"
  ln -sf "$LIB/artifactbay" "$BIN/artifactbay"
  good "CLI + MCP server installed"

  case ":$PATH:" in
    *":$BIN:"*) : ;;
    *) warn "$BIN is not on your PATH — add it:"
       note "echo 'export PATH=\"$BIN:\$PATH\"' >> ~/.profile" ;;
  esac

  # Point it at an instance. `init` verifies the key before writing the config.
  if [ -n "$KEY" ]; then
    [ -n "$URL" ] || URL="${BASE_URL:-http://localhost:$PORT}"
    LOCAL="http://localhost:$PORT"
    if try_init "$URL"; then
      good "configured for $URL → ~/.config/artifactbay/config.json"
    elif [ "$MODE" != "client" ] && [ "$URL" != "$LOCAL" ] && try_init "$LOCAL"; then
      # Public origin isn't resolvable from here yet (proxy/DNS still to come),
      # but the stack we just started is. Share links still use ARTIFACTBAY_BASE_URL.
      good "configured for $LOCAL → ~/.config/artifactbay/config.json"
      note "$URL wasn't reachable from here yet; re-run init once it is"
    else
      warn "couldn't verify the key against $URL — finish with:"
      note "artifactbay init --url $URL --key $KEY"
    fi
  else
    note "point it at your instance:  artifactbay init --url <URL> --key ab_..."
    note "(create a key in the dashboard under Settings → API keys)"
  fi

  # ── 3. agents ──
  if [ "$WITH_MCP" -eq 1 ] && have claude; then
    if claude mcp add artifactbay --scope user -- python3 "$LIB/artifactbay_mcp.py" >/dev/null 2>&1; then
      good "registered the MCP server with Claude Code (user scope)"
    else
      note "MCP server already registered with Claude Code, or registration skipped"
    fi
  elif [ "$WITH_MCP" -eq 1 ]; then
    note "register with your agent:"
    note "claude mcp add artifactbay --scope user -- python3 $LIB/artifactbay_mcp.py"
    note "other agents (Codex, Cursor, OpenCode, Aider): $RAW/$REF/integrations/README.md"
  fi
  return 0
}

# ── run ──────────────────────────────────────────────────────────────────────

say ""
say "${B}ArtifactBay${R} ${DIM}— the persistent home for AI agent artifacts${R}"
say ""

case "$MODE" in
  all)    install_server; say ""; install_client ;;
  server) install_server ;;
  client) install_client ;;
esac

say ""
step "Done"
case "$MODE" in
  client) note "artifactbay doctor        # verify connectivity + auth" ;;
  *)      note "open ${BASE_URL:-http://localhost:$PORT}"
          note "artifactbay doctor        # verify connectivity + auth"
          note "artifactbay push report.html --name \"My first artifact\""
          note "stop/start:  (cd $DIR && docker compose -p $PROJECT -f $COMPOSE_FILE down|up -d)" ;;
esac
say ""
