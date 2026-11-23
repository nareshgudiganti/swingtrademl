#!/usr/bin/env bash
# Disk check for a release. Run by deploy.yml BEFORE it checks out the release commit (so a refused deploy
# leaves /root/app on the commit that is running, and the next deploy records the right previous commit),
# and again by release.sh. It only reads: it writes, builds and stops nothing.
set -euo pipefail
APP_DIR=${APP_DIR:-/root/app}
BACKUP_ROOT=${BACKUP_ROOT:-/root/backups}
# Refuse to start on a nearly full disk. This runs before anything is written, built or stopped: the build,
# the images kept for rollback and the database copy all need room, and a deploy that runs out of space
# half way (22 Nov) is far worse than one that never started.
# Every disk the release writes to is checked: /, the app folder, the backup folder and Docker's own storage
# (images, containers and the build cache live in Docker's root, which can be another disk). A disk that cannot
# be found or measured also stops the deploy: not knowing is not the same as having room.
MIN_FREE_GB=${MIN_FREE_GB:-5}
refuse() { echo "Deployment NOT started: $1 Nothing was changed and the site is untouched." >&2; exit 1; }
free_gb() { df -Pk "$1" | awk 'NR==2 { printf "%d", $4 / 1048576 }'; }
existing_dir() { p=$1; while [ ! -d "$p" ] && [ "$p" != / ]; do p=$(dirname "$p"); done; echo "$p"; }
check_free_space() { # $1 = a folder on the disk to check, $2 = what to call it in the message
  if ! free=$(free_gb "$1") || [ -z "$free" ]; then
    refuse "could not measure the free space on $2, so it cannot be sure there is room. Check the disk by hand and deploy again."
  fi
  case "$free" in
    *[!0-9]*) refuse "could not measure the free space on $2 (unreadable answer). Check the disk by hand and deploy again." ;;
  esac
  if awk -v f="$free" -v m="$MIN_FREE_GB" 'BEGIN { exit !(f < m) }'; then
    refuse "only ${free} GB free on $2, and at least ${MIN_FREE_GB} GB are needed (the build, the rollback images and the database copy all need room). Free some disk space (old Docker images, old backups) and deploy again."
  fi
}
docker_root=$(docker info --format '{{.DockerRootDir}}' 2>/dev/null) || docker_root=""
[ -n "$docker_root" ] || refuse "could not find where Docker keeps its data, so it cannot check that disk. Check that Docker is running and deploy again."
check_free_space / "the main disk (/)"
check_free_space "$APP_DIR" "the app disk ($APP_DIR)"
check_free_space "$(existing_dir "$BACKUP_ROOT")" "the backup disk ($BACKUP_ROOT)"
check_free_space "$docker_root" "Docker's own storage disk ($docker_root)"
