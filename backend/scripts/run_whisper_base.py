from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Run local Whisper on a video file.")
    parser.add_argument("input", help="Source video path")
    parser.add_argument("--job-id", default="manual")
    parser.add_argument("--material-id", default="")
    parser.add_argument("--fingerprint", default="")
    parser.add_argument("--model", default="base")
    parser.add_argument("--seconds", type=float, default=0.0, help="Seconds to transcribe; <= 0 means full video.")
    parser.add_argument("--model-cache", default=str(Path(__file__).resolve().parents[2] / "model-cache" / "whisper"))
    parser.add_argument("--output-dir", default=str(Path(__file__).resolve().parents[2] / "storage" / "asr"))
    parser.add_argument("--output-file", default="")
    parser.add_argument("--language", default="zh")
    args = parser.parse_args()

    source = Path(args.input)
    if not source.exists():
        raise FileNotFoundError(source)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    model_cache = Path(args.model_cache)
    model_cache.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix=f"videocut_asr_{args.job_id}_") as tmp:
        wav_path = Path(tmp) / "clip.wav"
        command = [
            "ffmpeg",
            "-y",
            "-i",
            str(source),
            "-vn",
            "-acodec",
            "pcm_s16le",
            "-ar",
            "16000",
            "-ac",
            "1",
            str(wav_path),
        ]
        if args.seconds > 0:
            command[4:4] = ["-t", str(args.seconds)]
        subprocess.run(command, check=True, capture_output=True)

        import whisper

        model = whisper.load_model(args.model, download_root=str(model_cache))
        result = model.transcribe(str(wav_path), language=args.language, fp16=False, verbose=False)

    payload = {
        "job_id": args.job_id,
        "material_id": args.material_id,
        "fingerprint": args.fingerprint,
        "source": str(source),
        "model": args.model,
        "seconds": args.seconds,
        "language": args.language,
        "text": result.get("text", "").strip(),
        "segments": [
            {
                "start": segment.get("start"),
                "end": segment.get("end"),
                "text": segment.get("text", "").strip(),
            }
            for segment in result.get("segments", [])
        ],
    }
    target = Path(args.output_file) if args.output_file else output_dir / f"{args.job_id}_{args.material_id or 'manual'}_whisper_{args.model}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
