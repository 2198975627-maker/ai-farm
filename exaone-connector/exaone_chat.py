"""Call K-EXAONE 2.5 chat completions via the registered custom.exaone credential.

Usage:
  python3 exaone_chat.py "What model are you? Please answer with your exact model name only."
  python3 exaone_chat.py --prompt "Hello" --max-tokens 200

The key is never in this file. dynamic_credentials.py places a surrogate
where the provider reads the key, and Muse swaps in the real credential
only on an approved request to api.exaone.ai.
K-EXAONE supports Korean and English only, so test prompts must be English.
"""
import argparse
import json
import sys
import urllib.request
import urllib.error

sys.path.insert(0, "/opt/muse/skills/custom-connector-setup/bin")
from dynamic_credentials import add_surrogate_to_request, read_json_response


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        raise RuntimeError("redirect refused, verify the endpoint")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("prompt", nargs="?", default="What model are you? Please answer with your exact model name only.")
    ap.add_argument("--prompt", dest="prompt_flag", default=None)
    ap.add_argument("--max-tokens", type=int, default=200)
    ap.add_argument("--model", default="k-exaone_v2.5")
    args = ap.parse_args()
    prompt = args.prompt_flag or args.prompt
    body = json.dumps({
        "model": args.model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": args.max_tokens,
    }).encode("utf-8")
    request = urllib.request.Request(
        "https://api.exaone.ai/v1/chat/completions",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    add_surrogate_to_request(request, "custom.exaone", allowed_hosts=["api.exaone.ai"])
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=90) as response:
            data = read_json_response(response)
            headers = dict(response.headers)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="ignore")[:1000]
        print(json.dumps({"error": f"HTTP {e.code}", "body": raw}, ensure_ascii=False, indent=2))
        return 1
    choices = data.get("choices") or []
    text = ""
    if choices:
        text = (choices[0].get("message") or {}).get("content") or ""
    remaining = {k: v for k, v in headers.items() if "rate-limit-remaining" in k.lower()}
    out = {
        "model": args.model,
        "text": text,
        "usage": data.get("usage") or {},
        "rate_limit_remaining": remaining,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
