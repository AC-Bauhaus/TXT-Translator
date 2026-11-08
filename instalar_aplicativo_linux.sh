#!/usr/bin/env bash
set -e
APP_DIR="$(cd "$(dirname "$0")" && pwd)"
if [ ! -x "$APP_DIR/.venv/bin/python" ]; then
  echo "Ambiente Python não encontrado. Criando e instalando as dependências (requer internet na primeira vez)..."
  python -m venv "$APP_DIR/.venv"
  "$APP_DIR/.venv/bin/python" -m pip install -r "$APP_DIR/requirements.txt"
fi
chmod +x "$APP_DIR/iniciar_linux.sh"
ICON_DIR="$HOME/.local/share/icons/hicolor/scalable/apps"
APP_DIRS="$HOME/.local/share/applications"
mkdir -p "$ICON_DIR" "$APP_DIRS"
cp "$APP_DIR/assets/txt-tradutor.svg" "$ICON_DIR/txt-tradutor.svg"
EXEC_PATH="$APP_DIR/iniciar_linux.sh"
EXEC_ESCAPED="$(printf '%s' "$EXEC_PATH" | sed 's/\\/\\\\/g; s/ /\\ /g')"
cat > "$APP_DIRS/txt-tradutor.desktop" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=TXT Tradutor Offline
Comment=Tradutor de arquivos TXT com modelos locais
Exec=$EXEC_ESCAPED
Icon=txt-tradutor
Terminal=false
Categories=Office;Utility;TextTools;
StartupNotify=true
EOF
chmod +x "$APP_DIRS/txt-tradutor.desktop"
if command -v update-desktop-database >/dev/null 2>&1; then update-desktop-database "$APP_DIRS" || true; fi
echo "Atalho criado no menu de aplicativos: TXT Tradutor Offline"
echo "A tradução offline exige que os modelos de idioma desejados estejam instalados."
