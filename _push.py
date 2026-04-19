import subprocess, os
from dotenv import load_dotenv
load_dotenv()
token = os.environ["GITHUB_TOKEN"]
result = subprocess.run(
    ["git", "push", f"https://x-access-token:{token}@github.com/britalx/metrica.git", "master"],
    capture_output=True, text=True
)
print(result.stdout)
print(result.stderr)
print("Exit code:", result.returncode)
