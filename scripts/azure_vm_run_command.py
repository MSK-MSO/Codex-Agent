#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import requests


DEFAULT_API_VERSION = "2024-07-01"
DEFAULT_CREDENTIALS_FILE = "~/.config/mso-codex/azure-vm-run-command.json"


class AzureError(RuntimeError):
    pass


def _env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip()
    return value if value else default


def _load_json_file(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    expanded = Path(path).expanduser()
    try:
        with expanded.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return {}
    if not isinstance(data, dict):
        raise AzureError(f"Credential file is not a JSON object: {expanded}")
    return data


def _cfg_value(data: dict[str, Any], key: str) -> str | None:
    aliases = {
        "tenantId": ("tenantId", "AZURE_TENANT_ID", "MS_TENANT_ID"),
        "clientId": ("clientId", "AZURE_CLIENT_ID"),
        "clientSecret": ("clientSecret", "AZURE_CLIENT_SECRET"),
        "subscriptionId": ("subscriptionId", "AZURE_SUBSCRIPTION_ID"),
        "resourceGroup": ("resourceGroup", "AZURE_RESOURCE_GROUP"),
        "vmName": ("vmName", "AZURE_VM_NAME"),
        "commandId": ("commandId", "AZURE_VM_COMMAND_ID"),
    }
    for candidate in aliases.get(key, (key,)):
        value = data.get(candidate)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _redact(value: str | None) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "***"
    return value[:4] + "..." + value[-4:]


class AzureClient:
    def __init__(
        self,
        *,
        tenant_id: str,
        client_id: str,
        client_secret: str,
        subscription_id: str,
        timeout: int,
    ) -> None:
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.client_secret = client_secret
        self.subscription_id = subscription_id
        self.timeout = timeout
        self.session = requests.Session()
        self._access_token: str | None = None
        self._access_token_expires_at = 0.0

    def token(self) -> str:
        now = time.time()
        if self._access_token and now < self._access_token_expires_at - 60:
            return self._access_token

        url = f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token"
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "client_credentials",
            "scope": "https://management.azure.com/.default",
        }
        resp = self.session.post(url, data=data, timeout=self.timeout)
        if resp.status_code >= 400:
            raise AzureError(f"Azure token request failed: {resp.status_code} {resp.text}")
        payload = resp.json()
        token = payload.get("access_token")
        if not token:
            raise AzureError(f"Azure token response did not include access_token: {payload}")
        self._access_token = token
        self._access_token_expires_at = now + int(payload.get("expires_in") or 3600)
        return token

    def request(self, method: str, url: str, *, json_body: Any | None = None) -> Any:
        headers = {
            "Authorization": f"Bearer {self.token()}",
            "Accept": "application/json",
        }
        if json_body is not None:
            headers["Content-Type"] = "application/json"
        resp = self.session.request(method, url, headers=headers, json=json_body, timeout=self.timeout)
        if resp.status_code == 202:
            return self._poll_async(resp)
        if resp.status_code >= 400:
            raise AzureError(f"Azure {method} {url} failed: {resp.status_code} {resp.text}")
        if not resp.content:
            return None
        return resp.json()

    def _poll_async(self, resp: requests.Response) -> Any:
        poll_url = resp.headers.get("Azure-AsyncOperation") or resp.headers.get("Location")
        if not poll_url:
            if not resp.content:
                return {"status": "Accepted"}
            return resp.json()

        deadline = time.time() + self.timeout
        last_payload: Any = None
        while time.time() < deadline:
            poll_resp = self.session.get(
                poll_url,
                headers={"Authorization": f"Bearer {self.token()}", "Accept": "application/json"},
                timeout=min(30, self.timeout),
            )
            if poll_resp.status_code >= 400:
                raise AzureError(f"Azure async poll failed: {poll_resp.status_code} {poll_resp.text}")
            last_payload = poll_resp.json() if poll_resp.content else {}
            status = str(last_payload.get("status") or "").casefold()
            if status in {"succeeded", "failed", "canceled", "cancelled"}:
                return last_payload
            time.sleep(5)
        raise AzureError(f"Timed out waiting for Azure async operation: {last_payload}")

    def vm_base_url(self, resource_group: str, vm_name: str) -> str:
        return (
            f"https://management.azure.com/subscriptions/{self.subscription_id}"
            f"/resourceGroups/{resource_group}/providers/Microsoft.Compute/virtualMachines/{vm_name}"
        )


def _build_client(args: argparse.Namespace, config: dict[str, Any]) -> AzureClient:
    tenant_id = _env("AZURE_TENANT_ID", _cfg_value(config, "tenantId") or _env("MS_TENANT_ID"))
    client_id = _env("AZURE_CLIENT_ID", _cfg_value(config, "clientId"))
    client_secret = _env("AZURE_CLIENT_SECRET", _cfg_value(config, "clientSecret"))
    subscription_id = _env("AZURE_SUBSCRIPTION_ID", _cfg_value(config, "subscriptionId"))

    missing = [
        name
        for name, value in [
            ("AZURE_TENANT_ID", tenant_id),
            ("AZURE_CLIENT_ID", client_id),
            ("AZURE_CLIENT_SECRET", client_secret),
            ("AZURE_SUBSCRIPTION_ID", subscription_id),
        ]
        if not value
    ]
    if missing:
        raise AzureError(
            "Missing Azure configuration: "
            + ", ".join(missing)
            + ". Set environment variables or create "
            + args.credentials_file
            + "."
        )

    return AzureClient(
        tenant_id=tenant_id or "",
        client_id=client_id or "",
        client_secret=client_secret or "",
        subscription_id=subscription_id or "",
        timeout=args.timeout,
    )


def _subscription_id(config: dict[str, Any]) -> str | None:
    return _env("AZURE_SUBSCRIPTION_ID", _cfg_value(config, "subscriptionId"))


def _target(args: argparse.Namespace, config: dict[str, Any]) -> tuple[str, str]:
    resource_group = args.resource_group or _env("AZURE_RESOURCE_GROUP", _cfg_value(config, "resourceGroup"))
    vm_name = args.vm_name or _env("AZURE_VM_NAME", _cfg_value(config, "vmName"))
    missing = [
        name
        for name, value in [("AZURE_RESOURCE_GROUP", resource_group), ("AZURE_VM_NAME", vm_name)]
        if not value
    ]
    if missing:
        raise AzureError("Missing VM target: " + ", ".join(missing))
    return resource_group or "", vm_name or ""


def _command_id(args: argparse.Namespace, config: dict[str, Any]) -> str:
    command_id = (
        args.command_id
        or _env("AZURE_VM_COMMAND_ID", _cfg_value(config, "commandId") or "RunShellScript")
        or "RunShellScript"
    )
    if command_id not in {"RunShellScript", "RunPowerShellScript"}:
        raise AzureError(f"Unsupported command ID: {command_id}")
    return command_id


def _read_script(args: argparse.Namespace) -> str:
    if bool(args.script) == bool(args.script_file):
        raise AzureError("Provide exactly one of --script or --script-file.")
    if args.script:
        return args.script
    return Path(args.script_file).read_text(encoding="utf-8")


def _parameters(values: list[str]) -> list[dict[str, str]]:
    params: list[dict[str, str]] = []
    for item in values:
        if "=" not in item:
            raise AzureError(f"Parameter must be name=value: {item}")
        name, value = item.split("=", 1)
        name = name.strip()
        if not name:
            raise AzureError(f"Parameter name cannot be empty: {item}")
        params.append({"name": name, "value": value})
    return params


def _print_messages(payload: Any) -> None:
    if not isinstance(payload, dict):
        print(json.dumps(payload, indent=2))
        return
    nested_output = payload.get("properties", {}).get("output") if isinstance(payload.get("properties"), dict) else None
    if isinstance(nested_output, dict):
        _print_messages(nested_output)
        return
    values = payload.get("value")
    if not isinstance(values, list):
        print(json.dumps(payload, indent=2))
        return
    for item in values:
        if not isinstance(item, dict):
            print(item)
            continue
        code = item.get("code")
        display = item.get("displayStatus")
        message = item.get("message")
        if code or display:
            print(" ".join(part for part in [str(code or ""), str(display or "")] if part).strip())
        if message:
            print(str(message).rstrip())


def _is_run_command_lock(exc: AzureError) -> bool:
    text = str(exc).casefold()
    return "409" in text and "run command extension execution is in progress" in text


def _invoke_with_conflict_retries(
    client: AzureClient,
    url: str,
    body: dict[str, Any],
    *,
    retries: int,
    delay_seconds: float,
) -> Any:
    attempts = retries + 1
    for attempt in range(1, attempts + 1):
        try:
            return client.request("POST", url, json_body=body)
        except AzureError as exc:
            if not _is_run_command_lock(exc) or attempt == attempts:
                raise
            print(
                "Invoke conflict: Azure Run Command is already in progress; "
                f"retrying in {delay_seconds:g}s ({attempt}/{attempts}).",
                file=sys.stderr,
            )
            time.sleep(delay_seconds)
    raise AzureError("unreachable retry state")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Call Azure VM Run Command without Azure CLI. Intended for Codex Cloud containers."
    )
    parser.add_argument(
        "--credentials-file",
        default=_env("AZURE_VM_CREDENTIALS_FILE", DEFAULT_CREDENTIALS_FILE),
        help="JSON credential file written by scripts/codex_setup_azure_vm_env.sh.",
    )
    parser.add_argument("-g", "--resource-group")
    parser.add_argument("-n", "--vm-name")
    parser.add_argument("--api-version", default=DEFAULT_API_VERSION)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--json", action="store_true", help="Print raw JSON.")

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("config", help="Print non-secret configuration.")
    subparsers.add_parser("show", help="Show VM instance view.")

    invoke = subparsers.add_parser("invoke", help="Run a shell or PowerShell script on a VM.")
    invoke.add_argument(
        "--command-id",
        default=None,
        choices=("RunShellScript", "RunPowerShellScript"),
    )
    invoke.add_argument("--script")
    invoke.add_argument("--script-file")
    invoke.add_argument("--parameter", action="append", default=[])
    invoke.add_argument("--dry-run", action="store_true")
    invoke.add_argument(
        "--conflict-retries",
        type=int,
        default=10,
        help="Retries for Azure's transient Run Command in-progress 409 lock.",
    )
    invoke.add_argument(
        "--conflict-delay-seconds",
        type=float,
        default=20,
        help="Delay between Run Command in-progress lock retries.",
    )

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        config = _load_json_file(args.credentials_file)

        if args.command == "config":
            data = {
                "tenantId": _env("AZURE_TENANT_ID", _cfg_value(config, "tenantId") or _env("MS_TENANT_ID")),
                "clientId": _redact(_env("AZURE_CLIENT_ID", _cfg_value(config, "clientId"))),
                "subscriptionId": _env("AZURE_SUBSCRIPTION_ID", _cfg_value(config, "subscriptionId")),
                "resourceGroup": args.resource_group
                or _env("AZURE_RESOURCE_GROUP", _cfg_value(config, "resourceGroup")),
                "vmName": args.vm_name or _env("AZURE_VM_NAME", _cfg_value(config, "vmName")),
                "commandId": _command_id(argparse.Namespace(command_id=None), config),
                "credentialsFile": str(Path(args.credentials_file).expanduser()),
            }
            print(json.dumps(data, indent=2))
            return 0

        resource_group, vm_name = _target(args, config)

        if args.command == "invoke" and args.dry_run:
            subscription_id = _subscription_id(config) or "SUBSCRIPTION_ID"
            base_url = (
                f"https://management.azure.com/subscriptions/{subscription_id}"
                f"/resourceGroups/{resource_group}/providers/Microsoft.Compute/virtualMachines/{vm_name}"
            )
            script = _read_script(args)
            body = {
                "commandId": _command_id(args, config),
                "script": [script],
                "parameters": _parameters(args.parameter),
            }
            url = f"{base_url}/runCommand?api-version={args.api_version}"
            print(json.dumps({"method": "POST", "url": url, "body": body}, indent=2))
            return 0

        client = _build_client(args, config)
        base_url = client.vm_base_url(resource_group, vm_name)

        if args.command == "show":
            url = f"{base_url}/instanceView?api-version={args.api_version}"
            payload = client.request("GET", url)
        elif args.command == "invoke":
            script = _read_script(args)
            body = {
                "commandId": _command_id(args, config),
                "script": [script],
                "parameters": _parameters(args.parameter),
            }
            url = f"{base_url}/runCommand?api-version={args.api_version}"
            payload = _invoke_with_conflict_retries(
                client,
                url,
                body,
                retries=max(args.conflict_retries, 0),
                delay_seconds=max(args.conflict_delay_seconds, 0),
            )
        else:
            parser.error(f"Unknown command: {args.command}")
            return 2

        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            _print_messages(payload)
        return 0
    except AzureError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except requests.RequestException as exc:
        print(f"network error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
