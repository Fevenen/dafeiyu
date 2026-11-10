"""Build the public source tree from a local customized Open-LLM-VTuber tree.
Only code and persona templates are copied. Never copies runtime data/config.
"""

import argparse
import shutil
from pathlib import Path

RUNTIME_FILES = (
    "routes.py",
    "websocket_handler.py",
    "conversations/single_conversation.py",
    "conversations/conversation_utils.py",
    "tts/sherpa_onnx_tts.py",
)


def sync(pet, release):
    source = pet / "bridge"
    for path in source.rglob("*"):
        if not path.is_file() or path.suffix not in (".py", ".md", ".yml"):
            continue
        if any(
            part in ("logs", "data", "state", "__pycache__")
            for part in path.relative_to(source).parts
        ):
            continue
        target = release / "bridge" / path.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    for name in RUNTIME_FILES:
        source = pet / "src/open_llm_vtuber" / name
        target = release / "runtime/open_llm_vtuber" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    shutil.copy2(pet / "LICENSE", release / "runtime/LICENSE-Open-LLM-VTuber")
    print(
        "Synced bridge and",
        len(RUNTIME_FILES),
        "runtime files; no private data copied.",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--pet", type=Path, default=Path(__file__).resolve().parents[2] / "pet"
    )
    parser.add_argument(
        "--release", type=Path, default=Path(__file__).resolve().parents[1]
    )
    args = parser.parse_args()
    sync(args.pet.resolve(), args.release.resolve())
