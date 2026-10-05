#!/usr/bin/env bash
# =====================================================================
#  sincroniza-media.sh  —  se ejecuta en el EC2
#
#  1) Trae de la Raspberry Pi (por Tailscale SSH) los vídeos y fotos YA
#     TERMINADOS y los borra de la Pi solo cuando se han copiado bien.
#  2) Convierte a H.264 (reproducible en el navegador) los vídeos que aún
#     no lo estén. Los ya convertidos se saltan.
#  3) Deja el resultado en un fichero de estado JSON (para consultarlo a
#     mano o, en el futuro, desde la PWA).
#
#  Uso:   sincroniza-media.sh [dron_id]        (por defecto dron-01)
#  Log:   /var/log/sar-sync/sincroniza-<dron_id>.log
#  Estado:/var/lib/sar-sync/estado-<dron_id>.json
# =====================================================================
set -uo pipefail
 
# ------------------------- CONFIGURACIÓN -----------------------------
DRON_ID="${1:-dron-01}"
 
# Nombre en Tailscale de cada dron (como sale en 'tailscale status').
declare -A HOST_TAILSCALE=(
  [dron-01]="sar-drone"
  [dron-02]="dron-02"
)
PI_USER="nerea"                                          # usuario en la Pi
PI_RESULTS="/home/nerea/drone-edge-companion/results"    # carpeta results/ en la Pi
DESTINO="/var/www/html/results"                          # carpeta servida por nginx en el EC2
CARPETAS=(videos fotos)
 
DIR_ESTADO="/var/lib/sar-sync"
DIR_LOG="/var/log/sar-sync"
# ---------------------------------------------------------------------
 
HOST="${HOST_TAILSCALE[$DRON_ID]:-}"
if [ -z "$HOST" ]; then
  echo "dron_id desconocido: $DRON_ID" >&2
  exit 2
fi
 
mkdir -p "$DIR_ESTADO" "$DIR_LOG"
ESTADO="$DIR_ESTADO/estado-$DRON_ID.json"
LOG="$DIR_LOG/sincroniza-$DRON_ID.log"
exec >>"$LOG" 2>&1
 
# Origen: la Pi por SSH. (ORIGEN_PRUEBAS permite probar el script con una
# carpeta local en lugar de la Pi; en uso normal no se define.)
ORIGEN="${ORIGEN_PRUEBAS:-$PI_USER@$HOST:$PI_RESULTS}"
 
# Una sola sincronización a la vez por dron. Si ya hay una en marcha, se
# sale SIN tocar el fichero de estado (que sigue diciendo "en_curso").
exec 9>"$DIR_ESTADO/.lock-$DRON_ID"
if ! flock -n 9; then
  echo "$(date -Is) Ya hay una sincronización en curso para $DRON_ID; no se lanza otra."
  exit 0
fi
 
INICIO="$(date -Is)"
 
escribe_estado() {   # estado  copiados_videos  copiados_fotos  convertidos  mensaje
  local tmp="$ESTADO.tmp"
  printf '{"dron_id":"%s","estado":"%s","inicio":"%s","fin":"%s","videos_copiados":%s,"fotos_copiadas":%s,"videos_convertidos":%s,"mensaje":"%s"}\n' \
    "$DRON_ID" "$1" "$INICIO" "$(date -Is)" "$2" "$3" "$4" "${5//\"/\'}" >"$tmp"
  mv -f "$tmp" "$ESTADO"     # sustitución atómica: nunca se lee un JSON a medias
}
 
echo "===== $INICIO  Sincronización de $DRON_ID ($ORIGEN) ====="
escribe_estado "en_curso" 0 0 0 "Sincronizando"
 
# ----------------------- 1) SINCRONIZACIÓN ---------------------------
declare -A COPIADOS=([videos]=0 [fotos]=0)
ERRORES=()
 
for c in "${CARPETAS[@]}"; do
  mkdir -p "$DESTINO/$c"
  lista="$(mktemp)"
  # -a                     conserva fechas y permisos
  # --remove-source-files  borra en la Pi SOLO lo que se ha copiado y verificado bien
  # --partial-dir          si se corta, guarda lo descargado en una carpeta oculta
  #                        y la próxima vez continúa desde ahí (no empieza de cero)
  # --exclude=en_curso/    nunca se copia lo que la Pi aún está grabando
  # --timeout=120          si la conexión se queda colgada 2 min, se aborta
  # --out-format=%n        escribe el nombre de cada fichero copiado (para contarlos)
  timeout 30m rsync -a --remove-source-files \
        --partial-dir=.rsync-partial --exclude='en_curso/' --exclude='.rsync-partial/' \
        --timeout=120 --out-format='%n' \
        -e "ssh -o BatchMode=yes -o ConnectTimeout=15 -o ServerAliveInterval=15 -o ServerAliveCountMax=4" \
        "$ORIGEN/$c/" "$DESTINO/$c/" >"$lista"
  rc=$?
  cat "$lista"
  COPIADOS[$c]=$(grep -cv '/$' "$lista" || true)   # ficheros (no carpetas) copiados
  rm -f "$lista"
 
  case $rc in
    0|24) ;;   # 24 = algún fichero desapareció durante la copia: no es un error real
    255|12|14|124)
       ERRORES+=("$c: no se pudo conectar con $HOST (¿Pi apagada, sin red o Tailscale pidiendo autenticación?) [código $rc]") ;;
    23)
       ERRORES+=("$c: copia parcial, algunos ficheros no se pudieron copiar [código 23]") ;;
    *)
       ERRORES+=("$c: rsync terminó con error [código $rc]") ;;
  esac
  echo "$c: ${COPIADOS[$c]} fichero(s) copiado(s), rsync código $rc"
done
 
# ----------------------- 2) CONVERSIÓN -------------------------------
CONVERTIDOS=0
cd "$DESTINO/videos" || exit 1
shopt -s nullglob
for f in *.mp4; do                     # el * no incluye ficheros ocultos (.tmp_*, .rsync-partial)
  codec=$(ffprobe -v error -select_streams v:0 -show_entries stream=codec_name \
                  -of csv=p=0 "$f" 2>/dev/null)
  [ "$codec" = "h264" ] && continue    # ya convertido antes
  if [ -z "$codec" ]; then
    echo "AVISO: $f no se puede leer (¿incompleto?); se salta."
    continue
  fi
  tmp=".tmp_$f"
  echo "Convirtiendo $f ($codec -> h264)..."
  if nice -n 10 ffmpeg -nostdin -loglevel error -y -i "$f" \
        -c:v libx264 -preset veryfast -crf 23 -pix_fmt yuv420p \
        -movflags +faststart -an "$tmp"; then
    mv -f "$tmp" "$f"                  # se sustituye de golpe: nginx nunca sirve uno a medias
    CONVERTIDOS=$((CONVERTIDOS + 1))
  else
    rm -f "$tmp"
    ERRORES+=("conversión: fallo al convertir $f")
  fi
done
 
# ----------------------- 3) RESULTADO --------------------------------
if [ ${#ERRORES[@]} -eq 0 ]; then
  escribe_estado "ok" "${COPIADOS[videos]}" "${COPIADOS[fotos]}" "$CONVERTIDOS" "Sincronización completada"
  echo "OK: ${COPIADOS[videos]} vídeo(s), ${COPIADOS[fotos]} foto(s), $CONVERTIDOS convertido(s)."
  exit 0
else
  msg="$(printf '%s; ' "${ERRORES[@]}")"; msg="${msg%; }"
  escribe_estado "error" "${COPIADOS[videos]}" "${COPIADOS[fotos]}" "$CONVERTIDOS" "$msg"
  echo "ERROR: $msg"
  exit 1
fi
