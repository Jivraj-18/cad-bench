#!/usr/bin/env python3
"""Install the repeatable benchmark self-loop in the current user's systemd."""
from pathlib import Path
import subprocess
ROOT=Path(__file__).resolve().parents[1]
units=Path.home()/'.config/systemd/user'
units.mkdir(parents=True,exist_ok=True)
service=(ROOT/'tools/cad-bench-pilot.service').read_text().replace(
    '/home/jivraj/experiments/cad-bench',str(ROOT))
timer=(ROOT/'tools/cad-bench-pilot.timer').read_text()
(units/'cad-bench-self-loop.service').write_text(service)
(units/'cad-bench-self-loop.timer').write_text(timer)
subprocess.run(['systemctl','--user','stop','cad-bench-pilot.timer'],check=False)
subprocess.run(['systemctl','--user','daemon-reload'],check=True)
subprocess.run(['systemctl','--user','enable','--now','cad-bench-self-loop.timer'],check=True)
subprocess.run(['systemctl','--user','list-timers','cad-bench-self-loop.timer','--no-pager'],check=True)
