function die () {
  local msg="$1"
  local code="${2:-1}"
  echo "ERROR: $msg" >&2
  return "$code" 2>/dev/null || exit "$code"
}

function get_date () {
  local date="${1:-$(date +"%Y%m%d")}"
  if ! [[ "$date" =~ ^[0-9]{8}$ ]]; then
    die "Error: DATE must be in YYYYMMDD format. Got: '$date'" 1
  fi
  echo $date
}

function get_letters () {
    SIZE=$1

    readonly VALID_SIZES=("full" "large" "medium" "small")
    : "${SIZE:?Error: SIZE must be set to 'full', 'large', 'medium', or 'small'}"

    if [[ ! " ${VALID_SIZES[*]} " =~ " ${SIZE} " ]]; then
        die "Error: Unknown SIZE: $SIZE. Valid options are: ${VALID_SIZES[*]}" 1
    fi

    case "$SIZE" in
      "full")   LETTERS='A-Z' ;;
      "large")  LETTERS='A-H' ;;
      "medium") LETTERS='I-I' ;;
      "small")  LETTERS='Z-Z' ;;
    esac

    echo ${LETTERS}
}

function check_kdb () {
    : "${QEXEC:?Error: QEXEC not set. Probably skipped sourcing config/kdbenv}"
}