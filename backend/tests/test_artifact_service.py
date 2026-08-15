from app.services.artifact_service import ArtifactError, ArtifactService

PNG_HEADER = b"\x89PNG\r\n\x1a\nrest-of-file"
PDF_HEADER = b"%PDF-1.4\nrest-of-file"
MP4_HEADER = b"\x00\x00\x00\x20ftypisom\x00\x00\x02\x00" + b"rest-of-file"
M4A_HEADER = b"\x00\x00\x00\x20ftypM4A \x00\x00\x02\x00" + b"rest-of-file"
MOV_HEADER = b"\x00\x00\x00\x14ftypqt  \x00\x00\x02\x00" + b"rest-of-file"
MP3_ID3_HEADER = b"ID3\x04\x00\x00\x00\x00\x00\x00rest-of-file"
MP3_FRAME_HEADER = b"\xff\xfb\x90\x64rest-of-file"


def make_service(tmp_path, max_bytes: int = 1024) -> ArtifactService:
    return ArtifactService(str(tmp_path / "storage"), "/prompt/artifacts", max_bytes)


def test_validate_name_rejects_traversal_and_control_chars() -> None:
    assert ArtifactService.validate_name("report.pdf") == "report.pdf"
    assert ArtifactService.validate_name("sub/report.pdf") == "sub/report.pdf"
    for bad in ("../escape", "", "x" * 2000, "bad\x00name", "/absolute"):
        try:
            ArtifactService.validate_name(bad)
        except ArtifactError:
            continue
        raise AssertionError(f"expected ArtifactError for {bad!r}")


def test_ensure_session_dir_creates_directory(tmp_path) -> None:
    service = make_service(tmp_path)
    session_dir = service.ensure_session_dir("1")
    assert session_dir.is_dir()
    assert session_dir == service.storage_root / "1"


def test_prompt_path_uses_prompt_root(tmp_path) -> None:
    service = make_service(tmp_path)
    assert service.prompt_path("1") == "/prompt/artifacts/1"


def test_list_returns_only_recognized_files_within_size_limit(tmp_path) -> None:
    service = make_service(tmp_path, max_bytes=32)
    session_dir = service.ensure_session_dir("1")
    (session_dir / "photo.png").write_bytes(PNG_HEADER)
    (session_dir / "note.txt").write_text("hello world", encoding="utf-8")
    (session_dir / "unknown.bin").write_bytes(b"\x01\x02\x03\x04")
    (session_dir / "too-big.txt").write_text("x" * 64, encoding="utf-8")
    (session_dir / "empty.txt").write_bytes(b"")
    (session_dir / "clip.mp4").write_bytes(MP4_HEADER)
    (session_dir / "recording.mp3").write_bytes(MP3_ID3_HEADER)
    (session_dir / "memo.m4a").write_bytes(M4A_HEADER)
    sub_dir = session_dir / "screenshot"
    sub_dir.mkdir()
    (sub_dir / "shot.png").write_bytes(PNG_HEADER)

    artifacts = {item.name: item for item in service.list("1")}
    assert set(artifacts) == {
        "photo.png",
        "note.txt",
        "screenshot/shot.png",
        "clip.mp4",
        "recording.mp3",
        "memo.m4a",
    }
    assert artifacts["photo.png"].media_type == "image/png"
    assert artifacts["note.txt"].media_type == "text/plain"
    assert artifacts["screenshot/shot.png"].media_type == "image/png"
    assert artifacts["clip.mp4"].media_type == "video/mp4"
    assert artifacts["clip.mp4"].size == len(MP4_HEADER)
    assert artifacts["recording.mp3"].media_type == "audio/mpeg"
    assert artifacts["memo.m4a"].media_type == "audio/mp4"


def test_list_returns_empty_for_missing_session_dir(tmp_path) -> None:
    service = make_service(tmp_path)
    assert service.list("does-not-exist") == []


def test_get_returns_artifact_for_valid_file(tmp_path) -> None:
    service = make_service(tmp_path)
    session_dir = service.ensure_session_dir("1")
    (session_dir / "doc.pdf").write_bytes(PDF_HEADER)
    artifact = service.get("1", "doc.pdf")
    assert artifact.name == "doc.pdf"
    assert artifact.media_type == "application/pdf"
    assert artifact.size == len(PDF_HEADER)


def test_list_and_get_recognize_mp4_ftyp_box(tmp_path) -> None:
    service = make_service(tmp_path)
    session_dir = service.ensure_session_dir("1")
    (session_dir / "clip.mp4").write_bytes(MP4_HEADER)

    artifacts = {item.name: item for item in service.list("1")}
    assert artifacts["clip.mp4"].media_type == "video/mp4"

    artifact = service.get("1", "clip.mp4")
    assert artifact.media_type == "video/mp4"
    assert artifact.size == len(MP4_HEADER)


def test_list_and_get_recognize_m4a_ftyp_box(tmp_path) -> None:
    service = make_service(tmp_path)
    session_dir = service.ensure_session_dir("1")
    (session_dir / "memo.m4a").write_bytes(M4A_HEADER)

    artifacts = {item.name: item for item in service.list("1")}
    assert artifacts["memo.m4a"].media_type == "audio/mp4"
    assert service.get("1", "memo.m4a").media_type == "audio/mp4"


def test_sniff_rejects_iso_bmff_brands_outside_mp4_whitelist(tmp_path) -> None:
    service = make_service(tmp_path)
    session_dir = service.ensure_session_dir("1")
    (session_dir / "movie.mov").write_bytes(MOV_HEADER)

    assert service._sniff(session_dir / "movie.mov") is None
    assert service.list("1") == []


def test_list_and_get_recognize_mp3_id3_and_frame_signatures(tmp_path) -> None:
    service = make_service(tmp_path)
    session_dir = service.ensure_session_dir("1")
    (session_dir / "tagged.mp3").write_bytes(MP3_ID3_HEADER)
    (session_dir / "untagged.mp3").write_bytes(MP3_FRAME_HEADER)
    (session_dir / "fake.mp3").write_bytes(b"not really audio")

    artifacts = {item.name: item for item in service.list("1")}
    assert set(artifacts) == {"tagged.mp3", "untagged.mp3"}
    assert artifacts["tagged.mp3"].media_type == "audio/mpeg"
    assert service.get("1", "untagged.mp3").media_type == "audio/mpeg"


def test_get_rejects_path_traversal(tmp_path) -> None:
    service = make_service(tmp_path)
    session_dir = service.ensure_session_dir("1")
    secret = service.storage_root / "secret.txt"
    secret.write_text("top secret", encoding="utf-8")
    (session_dir / "safe.txt").write_text("ok", encoding="utf-8")

    for name in ("..", "../secret.txt", "missing.txt"):
        try:
            service.get("1", name)
        except ArtifactError:
            continue
        raise AssertionError(f"expected ArtifactError for {name!r}")


def test_delete_all_for_session_removes_directory(tmp_path) -> None:
    service = make_service(tmp_path)
    session_dir = service.ensure_session_dir("1")
    (session_dir / "a.txt").write_text("a", encoding="utf-8")
    (session_dir / "b.txt").write_text("b", encoding="utf-8")

    removed = service.delete_all_for_session("1")
    assert removed == 2
    assert not session_dir.exists()


def test_delete_all_for_session_is_noop_when_missing(tmp_path) -> None:
    service = make_service(tmp_path)
    assert service.delete_all_for_session("does-not-exist") == 0


def test_archive_for_session_moves_directory(tmp_path) -> None:
    service = make_service(tmp_path)
    session_dir = service.ensure_session_dir("1")
    (session_dir / "photo.png").write_bytes(PNG_HEADER)
    (session_dir / "note.txt").write_text("hello", encoding="utf-8")

    count = service.archive_for_session("1", "archive-uuid-1")
    assert count == 2
    assert not session_dir.exists()
    archive_dir = service.storage_root / "_archived" / "archive-uuid-1"
    assert archive_dir.is_dir()
    assert (archive_dir / "photo.png").read_bytes() == PNG_HEADER
    assert (archive_dir / "note.txt").read_text(encoding="utf-8") == "hello"


def test_archive_for_session_is_noop_when_missing(tmp_path) -> None:
    service = make_service(tmp_path)
    assert service.archive_for_session("does-not-exist", "archive-uuid-2") == 0


def test_restore_from_archive_moves_back(tmp_path) -> None:
    service = make_service(tmp_path)
    session_dir = service.ensure_session_dir("1")
    (session_dir / "photo.png").write_bytes(PNG_HEADER)
    service.archive_for_session("1", "archive-uuid-3")
    assert not session_dir.exists()

    service.restore_from_archive("archive-uuid-3", "2")
    new_dir = service.storage_root / "2"
    assert new_dir.is_dir()
    assert (new_dir / "photo.png").read_bytes() == PNG_HEADER
    assert not (service.storage_root / "_archived" / "archive-uuid-3").exists()


def test_restore_from_archive_is_noop_when_missing(tmp_path) -> None:
    service = make_service(tmp_path)
    service.restore_from_archive("nonexistent", "5")
    assert not (service.storage_root / "5").exists()


def test_delete_archived_removes_directory(tmp_path) -> None:
    service = make_service(tmp_path)
    session_dir = service.ensure_session_dir("1")
    (session_dir / "photo.png").write_bytes(PNG_HEADER)
    service.archive_for_session("1", "archive-uuid-4")
    archive_dir = service.storage_root / "_archived" / "archive-uuid-4"
    assert archive_dir.is_dir()

    service.delete_archived("archive-uuid-4")
    assert not archive_dir.exists()


def test_delete_archived_is_noop_when_missing(tmp_path) -> None:
    service = make_service(tmp_path)
    service.delete_archived("nonexistent")  # should not raise


def test_archive_restore_roundtrip_preserves_nested_files(tmp_path) -> None:
    service = make_service(tmp_path)
    session_dir = service.ensure_session_dir("1")
    sub = session_dir / "subdir"
    sub.mkdir()
    (session_dir / "root.png").write_bytes(PNG_HEADER)
    (sub / "nested.txt").write_text("nested content", encoding="utf-8")

    count = service.archive_for_session("1", "archive-uuid-5")
    assert count == 2

    service.restore_from_archive("archive-uuid-5", "99")
    restored = service.storage_root / "99"
    assert (restored / "root.png").read_bytes() == PNG_HEADER
    assert (restored / "subdir" / "nested.txt").read_text(encoding="utf-8") == "nested content"
