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


if __name__ == "__main__":
    unittest.main()
