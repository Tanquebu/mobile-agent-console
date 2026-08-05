import json
import shutil
import subprocess
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).parents[2]
UNIT_DIRECTORY = REPOSITORY_ROOT / "deploy" / "systemd"
UNITS = [
    UNIT_DIRECTORY / "mobile-agent-console-host-observability-prepare.service",
    UNIT_DIRECTORY / "mobile-agent-console-host-observability.socket",
    UNIT_DIRECTORY / "mobile-agent-console-host-observability@.service",
    UNIT_DIRECTORY / "mobile-agent-console-docker-state.service",
    UNIT_DIRECTORY / "mobile-agent-console-docker-state.timer",
    UNIT_DIRECTORY / "mobile-agent-console-service-state.service",
    UNIT_DIRECTORY / "mobile-agent-console-service-state.timer",
]
# Le due unit di raccolta fuori banda condividono la stessa eccezione di
# hardening e la stessa ragione: ADR 011 per Docker, ADR 012 per systemd e pm2.
OUT_OF_BAND_UNITS = [
    ("mobile-agent-console-docker-state", "docker"),
    ("mobile-agent-console-service-state", "services"),
]
# Ognuna di queste crea un mount namespace, e su Ubuntu 24.04 questo fa ricadere
# il servizio nel profilo AppArmor `unprivileged_userns`, che nega la connect()
# sul socket Docker rootless (ADR 011).
MOUNT_NAMESPACE_DIRECTIVES = [
    "PrivateTmp",
    "PrivateDevices",
    "PrivateMounts",
    "ProtectHome",
    "ProtectSystem",
    "ProtectKernelTunables",
    "ProtectControlGroups",
    "ReadOnlyPaths",
    "ReadWritePaths",
    "InaccessiblePaths",
]


class HostObservabilitySystemdTest(unittest.TestCase):
    def test_backend_test_mounts_shared_browser_fixtures_read_only(self) -> None:
        compose = (REPOSITORY_ROOT / "compose.yaml").read_text(encoding="utf-8")
        backend_test = compose.split("  backend-test:\n", 1)[1].split(
            "  frontend-build:\n", 1
        )[0]

        self.assertIn("source: ./frontend/tests/fixtures", backend_test)
        self.assertIn("target: /frontend/tests/fixtures", backend_test)
        self.assertIn("read_only: true", backend_test)
        production_backend = compose.split("  backend:\n", 1)[1].split("  web:\n", 1)[0]
        self.assertNotIn("frontend/tests/fixtures", production_backend)

    def test_user_transaction_has_no_ordering_cycle(self) -> None:
        systemd_analyze = shutil.which("systemd-analyze")
        if systemd_analyze is None:
            self.skipTest("systemd-analyze is unavailable")
        completed = subprocess.run(
            [systemd_analyze, "--user", "verify", *(str(unit) for unit in UNITS)],
            cwd=REPOSITORY_ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        diagnostics = f"{completed.stdout}\n{completed.stderr}"
        self.assertNotIn("ordering cycle", diagnostics.lower())
        self.assertNotIn("transaction order is cyclic", diagnostics.lower())
        self.assertEqual(completed.returncode, 0, diagnostics)

    def test_out_of_band_units_stay_out_of_a_mount_namespace(self) -> None:
        # Aggiungere qui una di queste direttive "per sicurezza" romperebbe la
        # raccolta in modo silenzioso: il collector tornerebbe a
        # `docker_unavailable` o `services_unavailable` senza che nulla lo dica.
        for name, _component in OUT_OF_BAND_UNITS:
            with self.subTest(unit=name):
                unit = (UNIT_DIRECTORY / f"{name}.service").read_text(encoding="utf-8")
                directives = [
                    line.split("=", 1)[0].strip()
                    for line in unit.splitlines()
                    if "=" in line and not line.lstrip().startswith("#")
                ]
                for forbidden in MOUNT_NAMESPACE_DIRECTIVES:
                    self.assertNotIn(forbidden, directives)
                self.assertIn("NoNewPrivileges", directives)
                self.assertIn("UMask", directives)
                self.assertIn("RuntimeMaxSec", directives)

    def test_host_observability_collector_keeps_full_hardening(self) -> None:
        # Il rovescio del test precedente: l'eccezione vale solo per la unit
        # Docker, il collector che legge /proc resta blindato.
        unit = (
            UNIT_DIRECTORY / "mobile-agent-console-host-observability@.service"
        ).read_text(encoding="utf-8")
        for required in ["PrivateTmp=yes", "ProtectHome=read-only", "ProtectSystem=strict"]:
            self.assertIn(required, unit)

    def test_out_of_band_timers_refresh_well_inside_the_staleness_limit(self) -> None:
        example = json.loads(
            (REPOSITORY_ROOT / "deploy" / "host-observability.example.json").read_text(
                encoding="utf-8"
            )
        )
        for name, component in OUT_OF_BAND_UNITS:
            with self.subTest(unit=name):
                timer = (UNIT_DIRECTORY / f"{name}.timer").read_text(encoding="utf-8")
                period = next(
                    int(line.split("=", 1)[1].removesuffix("s"))
                    for line in timer.splitlines()
                    if line.startswith("OnUnitActiveSec=")
                )
                # Tre tentativi prima che il dato diventi "non accertato": un
                # giro perso non deve far lampeggiare la dashboard.
                self.assertLessEqual(period * 3, example[component]["max_age_seconds"])

    def test_socket_service_uses_bounded_real_collector(self) -> None:
        service = (UNIT_DIRECTORY / "mobile-agent-console-host-observability@.service").read_text(
            encoding="utf-8"
        )
        self.assertIn("deploy/host-observability-collector.py", service)
        self.assertIn("RuntimeMaxSec=5", service)
        self.assertIn("RestrictAddressFamilies=AF_UNIX", service)
        # Le user unit partono già senza capability. Le direttive vuote
        # Capability* falliscono con 218/CAPABILITIES su manager rootless.
        self.assertNotIn("IPAddressDeny=", service)
        self.assertNotIn("CapabilityBoundingSet=", service)
        self.assertNotIn("AmbientCapabilities=", service)
        self.assertIn("ProtectSystem=strict", service)
        self.assertIn("ProtectHome=read-only", service)
        self.assertIn("PrivateTmp=yes", service)
        # Queste direttive richiedono operazioni di capability/namespace che
        # non sono applicabili in modo portabile da un manager user rootless.
        self.assertNotIn("PrivateDevices=", service)
        self.assertNotIn("ProtectClock=", service)
        self.assertNotIn("ProtectHostname=", service)
        self.assertNotIn("ProtectKernelLogs=", service)
        self.assertNotIn("ProtectKernelModules=", service)
        self.assertIn("RestrictNamespaces=yes", service)
        self.assertIn("RestrictSUIDSGID=yes", service)
        self.assertNotIn("User=root", service)
        self.assertNotIn("host-observability-spike.py", service)

    def test_socket_and_prepare_keep_minimal_permissions(self) -> None:
        socket = (UNIT_DIRECTORY / "mobile-agent-console-host-observability.socket").read_text(
            encoding="utf-8"
        )
        prepare = (
            UNIT_DIRECTORY / "mobile-agent-console-host-observability-prepare.service"
        ).read_text(encoding="utf-8")
        self.assertIn("SocketMode=0660", socket)
        self.assertIn("DirectoryMode=0750", socket)
        self.assertIn("MaxConnections=16", socket)
        self.assertIn("TriggerLimitBurst=30", socket)
        self.assertIn("NoNewPrivileges=yes", prepare)
        self.assertIn("RestrictAddressFamilies=AF_UNIX", prepare)
        self.assertNotIn("IPAddressDeny=", prepare)
        self.assertNotIn("CapabilityBoundingSet=", prepare)
        self.assertNotIn("AmbientCapabilities=", prepare)
        self.assertNotIn("User=root", prepare)
        # Queste direttive creano un mount namespace e romperebbero setfacl
        # sugli UID subordinati rootless; l'eccezione è intenzionale e documentata.
        self.assertNotIn("ProtectSystem=", prepare)
        self.assertNotIn("ProtectHome=", prepare)
        self.assertNotIn("PrivateTmp=", prepare)


class HostTmuxKeepaliveUnitTest(unittest.TestCase):
    """Regressioni di INC-HOST-01, tutte osservate su host reale il 05/08/2026."""

    def keepalive_service(self) -> str:
        # Solo le direttive: i commenti di questa unit citano per esteso le
        # direttive assenti, e cercarle nel testo grezzo darebbe falsi positivi.
        unit = (UNIT_DIRECTORY / "mobile-agent-console-tmux-host.service").read_text(
            encoding="utf-8"
        )
        return "\n".join(
            line for line in unit.splitlines() if not line.lstrip().startswith("#")
        )

    def test_keepalive_does_not_close_an_ordering_cycle(self) -> None:
        # Il WantedBy=default.target aggiunge gia' un Before=default.target
        # implicito: aggiungere anche After=default.target chiude un ciclo con
        # la unit compose, e systemd lo rompe cancellando proprio il job della
        # keepalive. Esito osservato: host acceso senza server tmux.
        unit = self.keepalive_service()
        self.assertIn("WantedBy=default.target", unit)
        self.assertNotIn("After=default.target", unit)

    def test_keepalive_never_kills_the_tmux_server_it_started(self) -> None:
        # `tmux new-session` lascia il SERVER nel cgroup della unit. Con il
        # KillMode di default ogni disattivazione (incluso ogni scatto del
        # timer) uccide il server e tutte le sessioni dell'utente, non solo la
        # keepalive. Senza RemainAfterExit questo diventa distruttivo a ogni
        # ciclo, quindi le due direttive vanno verificate insieme.
        unit = self.keepalive_service()
        self.assertIn("KillMode=process", unit)
        self.assertNotIn("RemainAfterExit=yes", unit)

    def test_keepalive_is_retried_while_the_host_stays_up(self) -> None:
        # In modalita' host il backend non avvia mai il server tmux (ADR 005):
        # se la keepalive sparisce a host acceso, creare sessioni resta rotto
        # fino al riavvio. Stesso rimedio di ADR 011: rieseguire l'oneshot.
        timer = (UNIT_DIRECTORY / "mobile-agent-console-tmux-host.timer").read_text(
            encoding="utf-8"
        )
        period = next(
            int(line.split("=", 1)[1].removesuffix("min")) * 60
            for line in timer.splitlines()
            if line.startswith("OnUnitActiveSec=")
        )
        self.assertLessEqual(period, 300)
        self.assertIn("WantedBy=timers.target", timer)


class ComposeOverlayUnitTest(unittest.TestCase):
    def test_compose_units_carry_the_optional_overlays(self) -> None:
        # docker compose NON legge COMPOSE_FILE dal file passato a --env-file:
        # senza questa variabile un riavvio dell'host ricrea i container privi
        # degli overlay opzionali, spegnendo le feature (Host sparito dalla UI
        # dopo il riavvio del 05/08/2026). Il "$" non graffato e' voluto:
        # systemd fa word splitting solo su quella forma.
        for name in ("mobile-agent-console-host", "mobile-agent-console-docker"):
            with self.subTest(unit=name):
                unit = (UNIT_DIRECTORY / f"{name}.service").read_text(encoding="utf-8")
                directives = [
                    line
                    for line in unit.splitlines()
                    if line.startswith(("ExecStart", "ExecReload", "ExecStop"))
                ]
                self.assertTrue(directives)
                for directive in directives:
                    self.assertIn("$MAC_COMPOSE_OVERLAYS ", directive)
                    self.assertNotIn("${MAC_COMPOSE_OVERLAYS}", directive)
        example = (UNIT_DIRECTORY / "environment.example").read_text(encoding="utf-8")
        self.assertIn("MAC_COMPOSE_OVERLAYS=", example)


if __name__ == "__main__":
    unittest.main()
