#!/usr/bin/env bash
#
# record-and-upload.sh -- Record a terminal demo and optionally upload to YouTube.
#
# Full pipeline:
#   1. Record terminal via asciinema  -> /tmp/delimit-demo.cast
#   2. Convert to GIF via agg         -> /tmp/delimit-demo.gif
#   3. Convert to MP4 via ffmpeg       -> /tmp/delimit-demo.mp4
#   4. Upload to YouTube via API       -> prints video URL
#
# Usage:
#   ./scripts/record-and-upload.sh [OPTIONS]
#
# Options:
#   --script <path>       Shell script to record (non-interactive). Omit for interactive.
#   --title <title>       YouTube video title (default: "Delimit Demo")
#   --description <desc>  YouTube video description
#   --gif-only            Only produce the GIF, skip MP4 and upload
#   --no-upload           Produce GIF + MP4 but skip YouTube upload
#   -h, --help            Show this help message
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --- Defaults ---
DEMO_SCRIPT=""
TITLE="Delimit Demo"
DESCRIPTION="API governance in action with Delimit CLI."
GIF_ONLY=false
NO_UPLOAD=false

CAST_FILE="/tmp/delimit-demo.cast"
GIF_FILE="/tmp/delimit-demo.gif"
MP4_FILE="/tmp/delimit-demo.mp4"

# --- Arg parsing ---
while [[ $# -gt 0 ]]; do
    case "$1" in
        --script)
            DEMO_SCRIPT="$2"
            shift 2
            ;;
        --title)
            TITLE="$2"
            shift 2
            ;;
        --description)
            DESCRIPTION="$2"
            shift 2
            ;;
        --gif-only)
            GIF_ONLY=true
            shift
            ;;
        --no-upload)
            NO_UPLOAD=true
            shift
            ;;
        -h|--help)
            head -25 "$0" | tail -22
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            exit 1
            ;;
    esac
done

# --- Step 1: Record with asciinema ---
echo "[record] Starting asciinema recording -> ${CAST_FILE}"
if [[ -n "${DEMO_SCRIPT}" ]]; then
    if [[ ! -f "${DEMO_SCRIPT}" ]]; then
        echo "Error: script not found: ${DEMO_SCRIPT}" >&2
        exit 1
    fi
    asciinema rec --overwrite --command "bash ${DEMO_SCRIPT}" "${CAST_FILE}"
else
    echo "[record] Interactive mode -- press Ctrl-D or type 'exit' when done."
    asciinema rec --overwrite "${CAST_FILE}"
fi
echo "[record] Recording saved to ${CAST_FILE}"

# --- Step 2: Convert to GIF via agg ---
echo "[gif] Converting cast -> GIF (theme: monokai, font-size: 16)"
agg --theme monokai --font-size 16 "${CAST_FILE}" "${GIF_FILE}"
echo "[gif] GIF saved to ${GIF_FILE}"

if [[ "${GIF_ONLY}" == true ]]; then
    echo "[done] GIF-only mode. Output: ${GIF_FILE}"
    exit 0
fi

# --- Step 3: Convert GIF to MP4 (YouTube Shorts: 1080x1920, 9:16) ---
echo "[mp4] Converting GIF -> MP4 (1080x1920, h264, Shorts-ready)"
ffmpeg -y -i "${GIF_FILE}" \
    -vf "scale='if(gt(iw/ih,1080/1920),1080,-2)':'if(gt(iw/ih,1080/1920),-2,1920)',pad=1080:1920:(1080-iw)/2:(1920-ih)/2:black" \
    -c:v libx264 \
    -pix_fmt yuv420p \
    -preset slow \
    -crf 18 \
    -movflags +faststart \
    -r 15 \
    "${MP4_FILE}"
echo "[mp4] MP4 saved to ${MP4_FILE}"

if [[ "${NO_UPLOAD}" == true ]]; then
    echo "[done] No-upload mode. Outputs:"
    echo "  GIF: ${GIF_FILE}"
    echo "  MP4: ${MP4_FILE}"
    exit 0
fi

# --- Step 4: Upload to YouTube ---
echo "[upload] Uploading to YouTube (unlisted) ..."
VIDEO_URL=$(python3 "${SCRIPT_DIR}/youtube-upload.py" \
    "${MP4_FILE}" \
    --title "${TITLE}" \
    --description "${DESCRIPTION}" \
    --privacy unlisted)

echo ""
echo "=============================="
echo " Pipeline complete"
echo "=============================="
echo " CAST: ${CAST_FILE}"
echo " GIF:  ${GIF_FILE}"
echo " MP4:  ${MP4_FILE}"
echo " URL:  ${VIDEO_URL}"
echo "=============================="
