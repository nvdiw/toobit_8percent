import psutil
import os
import threading
import time

class RamMonitor(threading.Thread):
    def __init__(self, interval=2, warn_mb=400):
        super().__init__(daemon=True)
        self.interval = interval
        self.warn_mb = warn_mb
        self.process = psutil.Process(os.getpid())
        self.running = True

    def run(self):
        while self.running:
            system_ram = psutil.virtual_memory()
            process_ram = self.process.memory_info().rss / (1024 ** 2)

            msg = (
                f"🖥 RAM {system_ram.percent}% | "
                f"🐍 Bot RAM: {process_ram:.1f} MB"
            )

            if process_ram > self.warn_mb:
                msg += " ⚠️ HIGH RAM"

            print(msg)
            time.sleep(self.interval)

    def stop(self):
        self.running = False
