import json

import pytest

from app.services.session_profile_service import (
    PROFILES,
    SessionProfileError,
    SessionProfileService,
)


def _service(tmp_path) -> SessionProfileService:
    return SessionProfileService(str(tmp_path / "session-profiles.json"))


def test_set_and_read_persist_across_instances(tmp_path) -> None:
    service = _service(tmp_path)
    service.set("2", "opencode_yolo")
    assert service.read() == {"2": "opencode_yolo"}

    # Il servizio è stateless: una nuova istanza sullo stesso path deve
    # ricaricare il profilo dal disco (simula il riavvio del backend).
    reloaded = _service(tmp_path)
    assert reloaded.read() == {"2": "opencode_yolo"}


def test_set_accumulates_entries(tmp_path) -> None:
    service = _service(tmp_path)
    service.set("1", "shell")
    service.set("2", "antigravity_yolo")
    assert service.read() == {"1": "shell", "2": "antigravity_yolo"}


def test_remove_deletes_only_the_requested_entry(tmp_path) -> None:
    service = _service(tmp_path)
    service.set("1", "shell")
    service.set("2", "codex")
    service.remove("2")
    assert service.read() == {"1": "shell"}
    # Rimuovere un id mai registrato è un no-op, non un errore.
    service.remove("9")
    assert service.read() == {"1": "shell"}


def test_read_filters_non_numeric_ids_and_unknown_profiles(tmp_path) -> None:
    path = tmp_path / "session-profiles.json"
    # Un file scritto a mano (o da una versione precedente) può contenere
    # entry non valide: id non numerici o vuoti e profili sconosciuti vanno
    # filtrati, non propagati.
    path.write_text(
        json.dumps(
            {
                "1": "opencode",
                "not-numeric": "shell",
                "": "shell",
                "2": "custom",
                "3": "shell",
            }
        ),
        encoding="utf-8",
    )
    service = _service(tmp_path)
    assert service.read() == {"1": "opencode", "3": "shell"}


def test_read_tolerates_corrupted_and_garbage_files(tmp_path) -> None:
    path = tmp_path / "session-profiles.json"
    path.write_text("{not valid json", encoding="utf-8")
    assert _service(tmp_path).read() == {}

    path.write_text('["not", "a", "dict"]', encoding="utf-8")
    assert _service(tmp_path).read() == {}

    path.unlink()
    assert _service(tmp_path).read() == {}


def test_set_rejects_invalid_profile_and_session_id(tmp_path) -> None:
    service = _service(tmp_path)
    with pytest.raises(SessionProfileError):
        service.set("1", "custom")
    with pytest.raises(SessionProfileError):
        service.set("not-numeric", "shell")
    with pytest.raises(SessionProfileError):
        service.set("", "shell")
    # Nessuna scrittura parziale sui rifiuti.
    assert not (tmp_path / "session-profiles.json").exists()
    assert not (tmp_path / "session-profiles.json.part").exists()


def test_write_is_atomic_and_leaves_no_part_file(tmp_path) -> None:
    service = _service(tmp_path)
    service.set("1", "claude")
    service.set("2", "shell")
    part = tmp_path / "session-profiles.json.part"
    assert not part.exists()
    assert _service(tmp_path).read() == {"1": "claude", "2": "shell"}


def test_all_profiles_are_roundtrippable(tmp_path) -> None:
    service = _service(tmp_path)
    for index, profile in enumerate(sorted(PROFILES)):
        service.set(str(index + 1), profile)
    assert service.read() == {
        str(index + 1): profile for index, profile in enumerate(sorted(PROFILES))
    }
