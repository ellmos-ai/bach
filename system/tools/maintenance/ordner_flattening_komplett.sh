#!/bin/bash
###############################################################################
# ORDNER-FLATTENING KOMPLETT
# Alle Phasen in einem Script. Kann komplett oder phasenweise ausgeführt werden.
#
# Nutzung:
#   bash _ordner_flattening_komplett.sh              # Alle Phasen
#   bash _ordner_flattening_komplett.sh --phase flatten
#   bash _ordner_flattening_komplett.sh --phase shorten
#   bash _ordner_flattening_komplett.sh --phase underscores
#   bash _ordner_flattening_komplett.sh --phase group
#   bash _ordner_flattening_komplett.sh --phase tripel
#   bash _ordner_flattening_komplett.sh --phase media
#   bash _ordner_flattening_komplett.sh --phase mixed_media
#   bash _ordner_flattening_komplett.sh --phase cleanup
###############################################################################

TARGET_DIR="${TARGET_DIR:-}"
if [ -z "$TARGET_DIR" ]; then
    echo "Bitte TARGET_DIR auf den lokalen Wissensdatenbank-Pfad setzen."
    exit 1
fi
cd "$TARGET_DIR" || { echo "Verzeichnis nicht gefunden!"; exit 1; }

PHASE_ARG="${1:-all}"
PHASE=""
[ "$PHASE_ARG" = "--phase" ] && PHASE="$2"
[ "$PHASE_ARG" = "all" ] && PHASE=""

run_phase() { [ -z "$PHASE" ] || [ "$PHASE" = "$1" ]; }

echo "============================================"
echo "  ORDNER-FLATTENING KOMPLETT"
echo "  Ziel: $TARGET_DIR"
echo "  Phase: ${PHASE:-ALLE}"
echo "  Start: $(date)"
echo "  Ordner vorher: $(ls -d */ 2>/dev/null | wc -l)"
echo "============================================"
echo ""

###############################################################################
# PHASE 1: FLATTEN - Alle Unterordner auf eine Ebene
###############################################################################
phase_flatten() {
    echo "=== PHASE 1: FLATTEN ==="
    local depth_before=$(find . -mindepth 2 -type d 2>/dev/null | wc -l)
    echo "Verschachtelte Ordner: $depth_before"

    while [ $(find . -mindepth 2 -maxdepth 2 -type d 2>/dev/null | wc -l) -gt 0 ]; do
        find . -mindepth 2 -maxdepth 2 -type d -print0 2>/dev/null | while IFS= read -r -d '' dir; do
            newname=$(echo "$dir" | sed 's|^\./||; s|/|_|g')
            mv "$dir" "./$newname" 2>/dev/null
        done
    done

    echo "Verschachtelte Ordner nachher: $(find . -mindepth 2 -type d 2>/dev/null | wc -l)"
    echo "Ordner gesamt: $(ls -d */ 2>/dev/null | wc -l)"
    echo ""
}

###############################################################################
# PHASE 2: KÜRZEN - Ordnernamen auf letztes Segment kürzen
###############################################################################
phase_shorten() {
    echo "=== PHASE 2: KÜRZEN ==="
    local count=0 merged=0

    for dir in */; do
        local dirname="${dir%/}"
        [[ "$dirname" != *_* ]] || [[ "$dirname" == _* ]] && continue

        local shortname="${dirname##*_}"
        [ -z "$shortname" ] && continue
        [ "$dirname" = "$shortname" ] && continue

        if [ -d "$shortname" ]; then
            cp -rn "$dirname"/* "$shortname"/ 2>/dev/null
            rm -rf "$dirname" 2>/dev/null
            ((merged++))
        else
            mv "$dirname" "$shortname" 2>/dev/null && ((count++))
        fi
    done

    echo "Umbenannt: $count, Gemerged: $merged"
    echo "Ordner gesamt: $(ls -d */ 2>/dev/null | wc -l)"
    echo ""
}

###############################################################################
# PHASE 3: UNTERSTRICHE BEREINIGEN - ___ und ____ auflösen
###############################################################################
phase_cleanup_underscores() {
    echo "=== PHASE 3: UNTERSTRICHE BEREINIGEN ==="
    local count=0

    # Mehrfach-Unterstriche auflösen
    for dir in */; do
        local dirname="${dir%/}"
        [[ "$dirname" == _* ]] && continue

        local shortname=""
        if [[ "$dirname" == *____* ]]; then
            shortname="${dirname##*____}"
        elif [[ "$dirname" == *___* ]]; then
            shortname="${dirname##*___}"
        elif [[ "$dirname" == *__* ]]; then
            shortname="${dirname##*__}"
        else
            continue
        fi

        [ -z "$shortname" ] || [ "$shortname" = "_" ] && {
            shortname="${dirname%__*}"
            shortname="${shortname##*_}"
        }
        [ -z "$shortname" ] && continue
        [ "$dirname" = "$shortname" ] && continue

        if [ -d "$shortname" ]; then
            cp -rn "$dirname"/* "$shortname"/ 2>/dev/null
            rm -rf "$dirname" 2>/dev/null
        else
            mv "$dirname" "$shortname" 2>/dev/null
        fi
        ((count++))
    done

    # Trailing Unterstriche entfernen
    for dir in */; do
        local dirname="${dir%/}"
        local shortname=$(echo "$dirname" | sed 's/_*$/')
        [ "$dirname" = "$shortname" ] && continue
        [ -z "$shortname" ] && continue

        if [ -d "$shortname" ]; then
            cp -rn "$dirname"/* "$shortname"/ 2>/dev/null
            rm -rf "$dirname" 2>/dev/null
        else
            mv "$dirname" "$shortname" 2>/dev/null
        fi
        ((count++))
    done

    echo "Bereinigt: $count"
    echo "Ordner gesamt: $(ls -d */ 2>/dev/null | wc -l)"
    echo ""
}

###############################################################################
# PHASE 4: GRUPPIEREN - Problematische Ordner in Sammelordner
###############################################################################
phase_group_problematic() {
    echo "=== PHASE 4: GRUPPIEREN ==="

    mkdir -p "_Musik-Genres" "_Veranstaltungen_Termine" "_Sitzungen_Module" \
             "_FoBi-Termine" "_CD-Sammlungen" "_Kurznamen_Diverses" \
             "_Nummerierte_Kapitel" "_Verwaltung_Prozesse" "_Altersgruppen" \
             "_Musik_Klassik" "_Hörspiele_Serien" 2>/dev/null

    local moved=0

    for dir in */; do
        local dirname="${dir%/}"
        [[ "$dirname" == _* ]] && continue

        # Musik-Genres (beginnen mit "0 ")
        if [[ "$dirname" == "0 "* ]]; then
            mv "$dirname" "_Musik-Genres/" 2>/dev/null && ((moved++))
            continue
        fi

        # CD-Ordner
        if [[ "$dirname" == CD* ]] && [[ "$dirname" =~ ^CD[[:space:]]?[0-9] ]]; then
            mv "$dirname" "_CD-Sammlungen/" 2>/dev/null && ((moved++))
            continue
        fi

        # FoBi-Termine (2022-xx-xx, 2023-xx-xx, etc.)
        if [[ "$dirname" =~ ^20[0-9]{2}-[0-9]{2} ]]; then
            mv "$dirname" "_FoBi-Termine/" 2>/dev/null && ((moved++))
            continue
        fi

        # Veranstaltungstermine (08-xx, 09-xx)
        if [[ "$dirname" =~ ^0[89]-[0-9]{2} ]]; then
            mv "$dirname" "_Veranstaltungen_Termine/" 2>/dev/null && ((moved++))
            continue
        fi

        # Altersgruppen (xM-xJ, x-xJ)
        if [[ "$dirname" =~ ^[0-9]+M-[0-9]+J$ ]] || [[ "$dirname" =~ ^[0-9]+-[0-9]+J$ ]]; then
            mv "$dirname" "_Altersgruppen/" 2>/dev/null && ((moved++))
            continue
        fi

        # Reine Jahreszahlen
        if [[ "$dirname" =~ ^20[0-9]{2}$ ]]; then
            mv "$dirname" "_FoBi-Termine/" 2>/dev/null && ((moved++))
            continue
        fi

        # 2-Zeichen-Ordner (aber nicht mit Leerzeichen)
        if [ ${#dirname} -le 2 ] && [[ "$dirname" != *" "* ]]; then
            mv "$dirname" "_Kurznamen_Diverses/" 2>/dev/null && ((moved++))
            continue
        fi
    done

    echo "Verschoben: $moved"
    echo "Ordner gesamt: $(ls -d */ 2>/dev/null | wc -l)"
    echo ""
}

###############################################################################
# PHASE 5: TRIPEL-ANALYSE (v2 - mit 8-Zeichen-Regel, Neustart, Normalisierung)
###############################################################################

# Normalisierung: Umlaute + Plural -> einheitliche Form
normalize() {
    echo "$1" | sed \
        -e 's/äu/au/g' -e 's/Äu/Au/g' \
        -e 's/ä/a/g' -e 's/Ä/A/g' \
        -e 's/ö/o/g' -e 's/Ö/O/g' \
        -e 's/ü/u/g' -e 's/Ü/U/g' \
        -e 's/ß/ss/g' \
    | tr '[:upper:]' '[:lower:]' \
    | sed \
        -e 's/ungen$/g' \
        -e 's/ionen$/g' \
        -e 's/nen$/g' \
        -e 's/ten$/g' \
        -e 's/sen$/g' \
        -e 's/en$/g' \
        -e 's/er$/g' \
        -e 's/es$/g' \
        -e 's/e$/g' \
        -e 's/s$/g'
}

# Match-Prüfung mit 8-Zeichen-Regel
is_match() {
    local short="$1"
    local other="$2"

    # Mindestlänge-Regel:
    # - Mit Leerzeichen (z.B. "ICF Katalog") -> ab 3 Zeichen OK
    # - Einwort ohne Leerzeichen (z.B. "Hand") -> mindestens 8 Zeichen
    if [[ "$short" == *" "* ]]; then
        [ ${#short} -lt 3 ] && return 1
    else
        [ ${#short} -lt 8 ] && return 1
    fi

    local short_lower=$(echo "$short" | tr '[:upper:]' '[:lower:]')
    local other_lower=$(echo "$other" | tr '[:upper:]' '[:lower:]')

    # 1) Exakter Substring (case-insensitive)
    [[ "$other_lower" == *"$short_lower"* ]] && return 0

    # 2) Normalisierter Substring (Raum=Räume, Teil=Teile)
    local short_norm=$(normalize "$short")
    local other_norm=$(normalize "$other")
    [ ${#short_norm} -ge 3 ] && [[ "$other_norm" == *"$short_norm"* ]] && return 0

    # 3) Erstes Wort gleich (normalisiert, nur >= 8 Zeichen)
    local short_w1=$(echo "$short_lower" | awk '{print $1}')
    local other_w1=$(echo "$other_lower" | awk '{print $1}')
    local short_w1n=$(normalize "$short_w1")
    local other_w1n=$(normalize "$other_w1")
    [ ${#short_w1n} -ge 8 ] && [ "$short_w1n" = "$other_w1n" ] && return 0

    return 1
}

phase_tripel_merge() {
    echo "=== PHASE 5: TRIPEL-ANALYSE (v2, abwärts mit Neustart) ==="

    local merged_total=0

    # Lade Ordnerliste
    mapfile -t folders < <(ls -d */ 2>/dev/null | sed 's/\/$/' | sort)
    local total=${#folders[@]}
    local i=0

    while [ $i -lt $((total - 2)) ]; do
        local f1="${folders[$i]}"
        local f2="${folders[$((i+1))]}"
        local f3="${folders[$((i+2))]}"

        # Existenz prüfen
        if [ ! -d "$f1" ] || [ ! -d "$f2" ] || [ ! -d "$f3" ]; then
            mapfile -t folders < <(ls -d */ 2>/dev/null | sed 's/\/$/' | sort)
            total=${#folders[@]}
            [ $i -ge $((total - 2)) ] && break
            continue
        fi

        # System-Ordner überspringen
        [[ "$f1" == _* ]] && ((i++)) && continue

        # Kürzesten finden
        local len1=${#f1} len2=${#f2} len3=${#f3}
        local shortest other1 other2

        if [ $len1 -le $len2 ] && [ $len1 -le $len3 ]; then
            shortest="$f1"; other1="$f2"; other2="$f3"
        elif [ $len2 -le $len1 ] && [ $len2 -le $len3 ]; then
            shortest="$f2"; other1="$f1"; other2="$f3"
        else
            shortest="$f3"; other1="$f1"; other2="$f2"
        fi

        local did_merge=0

        # Match other1 -> shortest?
        if [ -d "$other1" ] && [ -d "$shortest" ] && is_match "$shortest" "$other1"; then
            cp -rn "$other1"/* "$shortest"/ 2>/dev/null
            rm -rf "$other1" 2>/dev/null
            echo "Merged: $other1 -> $shortest"
            ((merged_total++))
            did_merge=1
        fi

        # Match other2 -> shortest?
        if [ -d "$other2" ] && [ -d "$shortest" ] && is_match "$shortest" "$other2"; then
            cp -rn "$other2"/* "$shortest"/ 2>/dev/null
            rm -rf "$other2" 2>/dev/null
            echo "Merged: $other2 -> $shortest"
            ((merged_total++))
            did_merge=1
        fi

        if [ $did_merge -eq 1 ]; then
            # NEUSTART: Liste neu laden, bei shortest weitermachen
            mapfile -t folders < <(ls -d */ 2>/dev/null | sed 's/\/$/' | sort)
            total=${#folders[@]}

            # Position von shortest finden
            local restart_i=-1
            for j in $(seq 0 $((total-1))); do
                [ "${folders[$j]}" = "$shortest" ] && { restart_i=$j; break; }
            done
            [ $restart_i -ge 0 ] && i=$restart_i || ((i++))
        else
            ((i++))
        fi
    done

    echo "Tripel-Merged: $merged_total"
    echo "Ordner gesamt: $(ls -d */ 2>/dev/null | wc -l)"
    echo ""
}

###############################################################################
# PHASE 6: MEDIENFORMAT-MERGE (Template-basiert)
# Ordner die ausschließlich Dateien eines Medientyps enthalten werden
# in einen Sammelordner verschoben. Erweiterbar für neue Formate.
###############################################################################

# Template: Medientyp-Definition
# Format: ZIELORDNER|EXTENSIONS (durch | getrennt)
# WICHTIG: Rekursive Prüfung - auch Ordner MIT Unterordnern werden erkannt
MEDIA_TYPES=(
    "_Audio|mp3|m4a|wav|flac|ogg|wma|aac|opus|aiff|aif|mid|midi|ape|mka|ra|ram|cda|mp2|wv|dsf|dff"
    "_Video|mp4|avi|mkv|mov|wmv|flv|webm|m4v|mpg|mpeg|3gp|vob|ts|mts|m2ts|rm|rmvb|ogv|asf|divx|f4v"
    "_Bilder|jpg|jpeg|png|gif|bmp|tiff|tif|webp|svg|ico|heic|heif|raw|cr2|nef|psd|ai|eps|jfif|avif|dng|arw|orf|rw2"
    # Weitere Typen hier ergänzen, z.B.:
    # "_Tabellen|xlsx|xls|csv|ods"
    # "_Prasentationen|pptx|ppt|odp"
    # "_Code|py|js|ts|sh|bat|ps1"
    # "_CAD|dwg|dxf|step|stl"
)

# Hilfsfunktion: Baut find-Pattern aus Extensions
build_find_pattern() {
    local exts="$1"
    local pattern=""
    local first=1
    IFS='|' read -ra ext_arr <<< "$exts"
    for ext in "${ext_arr[@]}"; do
        [ $first -eq 1 ] && first=0 || pattern="$pattern -o"
        pattern="$pattern -iname \"*.$ext\""
    done
    echo "$pattern"
}

phase_media_merge() {
    echo "=== PHASE 6: MEDIENFORMAT-MERGE ==="
    echo "(Rekursiv: prüft auch Ordner mit Unterordnern)"

    for media_def in "${MEDIA_TYPES[@]}"; do
        # Parse Definition: erstes Feld = Zielordner, Rest = Extensions
        IFS='|' read -ra parts <<< "$media_def"
        local target="${parts[0]}"
        # Extensions ab Index 1 wieder zusammenbauen
        local exts=$(IFS='|'; echo "${parts[*]:1}")

        mkdir -p "$target" 2>/dev/null
        local moved=0

        for dir in */; do
            local dirname="${dir%/}"
            [[ "$dirname" == _* ]] && continue

            # Alle Dateien rekursiv zählen (inkl. Unterordner)
            local total_files=$(find "$dirname" -type f 2>/dev/null | wc -l)
            [ "$total_files" -eq 0 ] && continue

            # Zähle Dateien dieses Medientyps (rekursiv)
            local media_files=0
            IFS='|' read -ra ext_arr <<< "$exts"
            for ext in "${ext_arr[@]}"; do
                local c=$(find "$dirname" -type f -iname "*.$ext" 2>/dev/null | wc -l)
                media_files=$((media_files + c))
            done

            # Rein dieses Formats? -> verschieben
            if [ "$media_files" -eq "$total_files" ] && [ "$media_files" -gt 0 ]; then
                mv "$dirname" "$target/$dirname" 2>/dev/null
                echo "$target: $dirname ($media_files Dateien)"
                ((moved++))
            fi
        done

        echo "${target}: $moved Ordner verschoben"
    done

    echo "Ordner gesamt: $(ls -d */ 2>/dev/null | wc -l)"
    echo ""
}

###############################################################################
# PHASE 6b: GEMISCHTE MEDIEN-ORDNER (Mehrheits-Regel)
# Ordner die NUR Mediendateien enthalten (aber gemischt: Audio+Video+Bilder)
# werden nach dem Mehrheitstyp sortiert.
###############################################################################
phase_mixed_media_merge() {
    echo "=== PHASE 6b: GEMISCHTE MEDIEN (Mehrheits-Regel) ==="

    # Alle Medien-Extensions zusammenbauen
    local ALL_AUDIO_EXT=(mp3 m4a wav flac ogg wma aac opus aiff aif mid midi ape mka ra ram cda mp2 wv dsf dff)
    local ALL_VIDEO_EXT=(mp4 avi mkv mov wmv flv webm m4v mpg mpeg 3gp vob ts mts m2ts rm rmvb ogv asf divx f4v)
    local ALL_BILDER_EXT=(jpg jpeg png gif bmp tiff tif webp svg ico heic heif raw cr2 nef psd ai eps jfif avif dng arw orf rw2)

    mkdir -p "_Audio" "_Video" "_Bilder" 2>/dev/null
    local moved=0

    for dir in */; do
        local dirname="${dir%/}"
        [[ "$dirname" == _* ]] && continue

        local total_files=$(find "$dirname" -type f 2>/dev/null | wc -l)
        [ "$total_files" -eq 0 ] && continue

        # Zähle jeden Medientyp
        local audio_count=0 video_count=0 bilder_count=0
        for ext in "${ALL_AUDIO_EXT[@]}"; do
            local c=$(find "$dirname" -type f -iname "*.$ext" 2>/dev/null | wc -l)
            audio_count=$((audio_count + c))
        done
        for ext in "${ALL_VIDEO_EXT[@]}"; do
            local c=$(find "$dirname" -type f -iname "*.$ext" 2>/dev/null | wc -l)
            video_count=$((video_count + c))
        done
        for ext in "${ALL_BILDER_EXT[@]}"; do
            local c=$(find "$dirname" -type f -iname "*.$ext" 2>/dev/null | wc -l)
            bilder_count=$((bilder_count + c))
        done

        local media_total=$((audio_count + video_count + bilder_count))

        # Nur wenn ALLE Dateien Medien sind (aber gemischt)
        [ "$media_total" -ne "$total_files" ] && continue
        [ "$media_total" -eq 0 ] && continue

        # Mehrheit bestimmen
        local target=""
        local max_count=$audio_count
        target="_Audio"

        if [ $video_count -gt $max_count ]; then
            max_count=$video_count
            target="_Video"
        fi
        if [ $bilder_count -gt $max_count ]; then
            max_count=$bilder_count
            target="_Bilder"
        fi

        mv "$dirname" "$target/$dirname" 2>/dev/null
        echo "$target: $dirname (A:$audio_count V:$video_count B:$bilder_count)"
        ((moved++))
    done

    echo "Gemischte Medien-Ordner verschoben: $moved"
    echo "Ordner gesamt: $(ls -d */ 2>/dev/null | wc -l)"
    echo ""
}

###############################################################################
# PHASE 7: LEERE ORDNER LÖSCHEN
###############################################################################
phase_cleanup_empty() {
    echo "=== PHASE 7: LEERE ORDNER LÖSCHEN ==="
    local empty=$(find . -mindepth 1 -maxdepth 1 -type d -empty 2>/dev/null | wc -l)
    find . -mindepth 1 -maxdepth 1 -type d -empty -delete 2>/dev/null
    echo "Gelöscht: $empty"
    echo "Ordner gesamt: $(ls -d */ 2>/dev/null | wc -l)"
    echo ""
}

###############################################################################
# AUSFÜHRUNG
###############################################################################

run_phase "flatten"      && phase_flatten
run_phase "shorten"      && phase_shorten
run_phase "underscores"  && phase_cleanup_underscores
run_phase "group"        && phase_group_problematic
run_phase "tripel"       && phase_tripel_merge
run_phase "media"        && phase_media_merge
run_phase "mixed_media"  && phase_mixed_media_merge
run_phase "cleanup"      && phase_cleanup_empty

echo "============================================"
echo "  FERTIG: $(date)"
echo "  Ordner final: $(ls -d */ 2>/dev/null | wc -l)"
echo "============================================"
