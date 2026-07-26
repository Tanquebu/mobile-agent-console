import argparse

from app.services.backup_service import BackupService


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Restore a Mobile Agent Console backup while the backend is stopped."
    )
    parser.add_argument("archive")
    parser.add_argument("--database", required=True)
    parser.add_argument("--snapshots", required=True)
    args = parser.parse_args()
    BackupService.restore(args.archive, args.database, args.snapshots)
    print("Backup restored and checksums verified.")


if __name__ == "__main__":
    main()
