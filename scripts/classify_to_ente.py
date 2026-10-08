"""Classify images headed to Ente: NSFW -> locked Hidden (.hidden), else requested album.

Runs the cached local NSFW ensemble (Falconsai + Marqo + Freepik) on CPU using
the dedicated .venv-classify, then queues each file through the ente-mcp CLI.

Usage:
  E:/development/ente-mcp/.venv-classify/Scripts/python.exe scripts/classify_to_ente.py PATH... [--album NAME] [--dry-run]

  --album     album for non-NSFW files (default Inbox)
  --dry-run   classify and print routing without queueing
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HARNESS_DIR = Path(r"E:/development/photo-classification-app/mac_nsfw_harness")
# ente-mcp.exe is the MCP server entry (ente_mcp.server), NOT the CLI; invoking it
# with CLI args silently exits 0 and queues nothing. Use the CLI via python -m.
ENTE_MCP_PY = ROOT / ".venv" / "Scripts" / "python.exe"


def cli_cmd(args: list[str]) -> list[str]:
    return [str(ENTE_MCP_PY), "-m", "ente_mcp.cli", *args]
FALCONSAI_MODEL = "Falconsai/nsfw_image_detection"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}

try:
    from ente_mcp.classify import classify_target_ensemble
except Exception:  # fallback when running under a venv without ente_mcp installed
    sys.path.insert(0, str(ROOT / "src"))

    from ente_mcp.classify import classify_target_ensemble

_classifier = None


def classify_image(path: Path) -> tuple[float, str]:
    """Return (ensemble_score, decision) for one image via the local NSFW ensemble on CPU."""
    global _classifier
    if _classifier is None:
        import torch
        from PIL import Image, ImageOps
        from transformers import AutoImageProcessor, AutoModelForImageClassification

        sys.path.insert(0, str(HARNESS_DIR))
        from run_ensemble import DEFAULT_MODELS, ensemble_decision, normalized_nsfw_score

        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        models: list[tuple[str, object, object, dict[int, str]]] = []
        for model_id in DEFAULT_MODELS:
            processor = AutoImageProcessor.from_pretrained(model_id)
            model = AutoModelForImageClassification.from_pretrained(model_id)
            model.to(device)
            model.eval()
            models.append((model_id, processor, model, model.config.id2label))
            print(f"Model {model_id} loaded", flush=True)
        _classifier = (torch, Image, ImageOps, device, models, normalized_nsfw_score, ensemble_decision)
        print(f"Ensemble ready on {device}", flush=True)

    torch, Image, ImageOps, device, models, normalized_nsfw_score, ensemble_decision = _classifier
    with Image.open(path) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGB")
        image.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
    model_rows: list[dict[str, object]] = []
    for model_id, processor, model, id_to_label in models:
        inputs = processor(images=image, return_tensors="pt")
        inputs = {key: value.to(device) for key, value in inputs.items()}
        with torch.inference_mode():
            logits = model(**inputs).logits
            probs = torch.softmax(logits, dim=-1)[0].detach().cpu().tolist()
        label_scores = {str(id_to_label[i]): float(score) for i, score in enumerate(probs)}
        score = float(normalized_nsfw_score(model_id, label_scores))
        model_rows.append({"model": model_id, "nsfw_score": score, "label_scores": label_scores})
    result = ensemble_decision(model_rows, 0.55)
    return float(result["ensemble_score"]), str(result["decision"])


def queue(path: Path, album: str) -> dict:
    if not ENTE_MCP_PY.is_file():
        return {"ok": False, "error": f"ente-mcp venv python not found: {ENTE_MCP_PY}"}
    result = subprocess.run(
        cli_cmd(["photos", "queue", str(path), "--album", album]),
        capture_output=True,
        text=True,
    )
    import json

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"ok": False, "stdout": result.stdout, "stderr": result.stderr, "returncode": result.returncode}


def main() -> int:
    parser = argparse.ArgumentParser(description="Queue files to Ente; NSFW images auto-route to .hidden")
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--album", default="Inbox", help="album for non-NSFW files (default Inbox)")
    parser.add_argument("--dry-run", action="store_true", help="classify and print routing without queueing")
    args = parser.parse_args()

    failures = 0
    for path in args.paths:
        if not path.is_file():
            print(f"[SKIP] missing: {path}")
            failures += 1
            continue
        if path.suffix.lower() not in IMAGE_SUFFIXES:
            print(f"[INFO] not an image ({path.suffix}), queuing to requested album {args.album}: {path.name}")
            album = args.album
        else:
            score, decision = classify_image(path)
            album = classify_target_ensemble(decision, score, args.album)
            print(f"[CLASSIFY] {path.name}: ensemble={score:.3f} ({decision}) -> album={album}")
        if args.dry_run:
            continue
        result = queue(path, album)
        queued = result.get("queued") or []
        skipped = result.get("skipped") or []
        if result.get("ok", True) and queued:
            print(f"[QUEUED] {path.name} -> {album}")
        elif queued and skipped:
            print(f"[QUEUED/NOTIFIED] {path.name} -> {album} ({len(queued)} queued, {len(skipped)} skipped)")
        else:
            print(f"[QUEUE FAILED] {path.name}: {result}")
            failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())