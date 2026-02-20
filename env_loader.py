import os


def load_dotenv_file(path=".env"):
    if not os.path.exists(path):
        return False

    with open(path, "r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip().lstrip("\ufeff")
            value = value.strip().strip("\"'")
            if not key:
                continue

            if key not in os.environ:
                os.environ[key] = value

    return True
