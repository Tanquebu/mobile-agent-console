#!/usr/bin/env python3
import json
import os

SPIKE_RESPONSE = {
    "schema_version": 1,
    "source": "socket-activation-spike",
    "status": "ok",
}


def main() -> None:
    # Con Accept=yes systemd collega il socket accettato a stdout. Lo spike non
    # legge input, non apre socket propri e non osserva ancora alcun dato host.
    payload = json.dumps(SPIKE_RESPONSE, separators=(",", ":")).encode("utf-8")
    os.write(1, payload)


if __name__ == "__main__":
    main()
