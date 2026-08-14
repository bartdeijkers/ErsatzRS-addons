#!/usr/bin/env python3
"""Build deterministic add-on packages and an unsigned v2 repository index."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pathlib
import re
import shutil
import tomllib
import zipfile

REPOSITORY_ID = "org.ersatzrs.addons.official"
REPOSITORY_NAME = "Official ErsatzRS add-ons"
PACKAGE_EPOCH = (2020, 1, 1, 0, 0, 0)
SUPPORTED_RIDS = {"linux-x64", "linux-arm64", "linux-arm", "osx-x64", "osx-arm64", "win-x64", "any"}
ENTRYPOINT_KINDS = {"native", "posix_shell", "windows_batch"}
SETTING_KINDS = {"string", "boolean", "integer", "enum", "path", "executable", "secret_reference"}
ROOT_FIELDS = {
    "manifest_version", "id", "version", "name", "summary", "license", "source_url",
    "host_version", "icon", "capabilities", "dependencies", "entrypoints", "permissions", "settings", "panels",
}
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
MAX_ICON_BYTES = 2 * 1024 * 1024


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sequence", required=True, type=int)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--output", required=True, type=pathlib.Path)
    parser.add_argument("--generated-at")
    parser.add_argument("--native-artifacts", type=pathlib.Path)
    return parser.parse_args()


def utc_timestamp(value: str | None) -> dt.datetime:
    if value is None:
        return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("--generated-at must include a timezone")
    return parsed.astimezone(dt.timezone.utc).replace(microsecond=0)


def rfc3339(value: dt.datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def package_files(addon_dir: pathlib.Path) -> list[pathlib.Path]:
    files = []
    for path in addon_dir.rglob("*"):
        relative = path.relative_to(addon_dir)
        if path.is_file() and not any(part.startswith(".") for part in relative.parts):
            files.append(path)
    return sorted(files, key=lambda path: path.relative_to(addon_dir).as_posix())


def validate_manifest(manifest: dict, addon_dir: pathlib.Path) -> None:
    unknown = set(manifest) - ROOT_FIELDS
    if unknown:
        raise ValueError(f"{addon_dir}: unknown manifest fields: {sorted(unknown)}")
    if manifest.get("manifest_version") not in {1, 2, 3}:
        raise ValueError(f"{addon_dir}: unsupported manifest version")
    icon = manifest.get("icon")
    if manifest.get("manifest_version") == 1 and icon is not None:
        raise ValueError(f"{addon_dir}: icons require manifest version 2")
    if icon is not None:
        if set(icon) != {"path", "media_type"} or icon.get("media_type") != "png":
            raise ValueError(f"{addon_dir}: invalid icon contract")
        icon_path = pathlib.PurePosixPath(icon.get("path", ""))
        source = addon_dir / icon_path
        if (
            not icon_path.as_posix()
            or icon_path.is_absolute()
            or ".." in icon_path.parts
            or not source.is_file()
            or source.stat().st_size > MAX_ICON_BYTES
            or not source.read_bytes().startswith(PNG_SIGNATURE)
        ):
            raise ValueError(f"{addon_dir}: invalid PNG icon")
    addon_id = manifest.get("id", "")
    parts = addon_id.split(".")
    if len(parts) < 3 or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", part) for part in parts):
        raise ValueError(f"{addon_dir}: invalid reverse-DNS id")
    if addon_id != addon_dir.name:
        raise ValueError(f"{addon_dir}: manifest id must equal directory name")
    for field in ("name", "summary"):
        if not str(manifest.get(field, {}).get("en-US", "")).strip():
            raise ValueError(f"{addon_dir}: {field} requires en-US")
    if not str(manifest.get("source_url", "")).startswith("https://"):
        raise ValueError(f"{addon_dir}: source URL must use HTTPS")
    capabilities = [item.get("id", "") for item in manifest.get("capabilities", [])]
    if "addon.check.v1" not in capabilities or len(capabilities) != len(set(capabilities)):
        raise ValueError(f"{addon_dir}: invalid capability set")
    if any(not re.fullmatch(r"[a-z0-9.-]+[.]v[0-9]+", item) for item in capabilities):
        raise ValueError(f"{addon_dir}: invalid capability id")
    dependencies = manifest.get("dependencies", [])
    dependency_ids = [item.get("id", "") for item in dependencies]
    if (
        len(dependencies) > 100
        or len(dependency_ids) != len(set(dependency_ids))
        or addon_id in dependency_ids
        or any(
            len(dependency_id.split(".")) < 3
            or any(
                not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", part)
                for part in dependency_id.split(".")
            )
            for dependency_id in dependency_ids
        )
        or any(not str(item.get("version", "")).strip() for item in dependencies)
    ):
        raise ValueError(f"{addon_dir}: invalid dependency set")
    entrypoints = manifest.get("entrypoints", {})
    if not entrypoints or set(entrypoints) - SUPPORTED_RIDS:
        raise ValueError(f"{addon_dir}: unsupported entrypoint RID")
    for entrypoint in entrypoints.values():
        path = entrypoint.get("path", "")
        entrypoint_path = pathlib.PurePosixPath(path)
        if (
            not path
            or entrypoint_path.is_absolute()
            or ".." in entrypoint_path.parts
            or entrypoint.get("kind") not in ENTRYPOINT_KINDS
            or (
                entrypoint.get("kind") != "native"
                and not (addon_dir / path).is_file()
            )
        ):
            raise ValueError(f"{addon_dir}: invalid entrypoint")
    settings = manifest.get("settings", [])
    keys = [setting.get("key", "") for setting in settings]
    if len(keys) != len(set(keys)) or any(not re.fullmatch(r"[A-Z][A-Z0-9_]*[A-Z0-9]", key) for key in keys):
        raise ValueError(f"{addon_dir}: invalid setting key")
    for setting in settings:
        kind = setting.get("kind")
        if kind not in SETTING_KINDS:
            raise ValueError(f"{addon_dir}: invalid setting kind")
        if kind == "secret_reference" and "default" in setting:
            raise ValueError(f"{addon_dir}: secret references cannot have defaults")
        suggested = setting.get("suggested_reference")
        if suggested is None:
            continue
        if manifest.get("manifest_version") < 3 or kind != "secret_reference":
            raise ValueError(f"{addon_dir}: invalid suggested secret reference")
        if set(suggested) != {"kind", "reference"} or suggested["kind"] not in {"environment", "file"}:
            raise ValueError(f"{addon_dir}: invalid suggested secret reference")
        reference = str(suggested["reference"])
        if not reference.strip() or (
            suggested["kind"] == "environment"
            and not re.fullmatch(r"[A-Z][A-Z0-9_]*[A-Z0-9]", reference)
        ):
            raise ValueError(f"{addon_dir}: invalid suggested secret reference")
    permissions = manifest.get("permissions", {})
    for command in permissions.get("external_commands", []):
        if not command or any(character in command for character in "/\\:") or any(character.isspace() for character in command):
            raise ValueError(f"{addon_dir}: invalid external command")


def write_package(
    root: pathlib.Path,
    addon_dir: pathlib.Path,
    destination: pathlib.Path,
    native_files: dict[str, pathlib.Path] | None = None,
) -> None:
    native_files = native_files or {}
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        license_info = zipfile.ZipInfo("LICENSE", PACKAGE_EPOCH)
        license_info.compress_type = zipfile.ZIP_DEFLATED
        license_info.external_attr = (0o644 & 0xFFFF) << 16
        archive.writestr(license_info, (root / "LICENSE").read_bytes())
        for path in package_files(addon_dir):
            relative = path.relative_to(addon_dir).as_posix()
            if relative == "LICENSE":
                continue
            info = zipfile.ZipInfo(relative, PACKAGE_EPOCH)
            info.compress_type = zipfile.ZIP_DEFLATED
            mode = 0o755 if path.suffix == ".sh" else 0o644
            info.external_attr = (mode & 0xFFFF) << 16
            contents = path.read_bytes()
            if path.suffix.lower() == ".bat":
                contents = contents.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
            archive.writestr(info, contents)
        for relative, path in sorted(native_files.items()):
            if not path.is_file():
                raise ValueError(f"missing native add-on artifact: {path}")
            info = zipfile.ZipInfo(relative, PACKAGE_EPOCH)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o755 & 0xFFFF) << 16
            archive.writestr(info, path.read_bytes())


def catalog_addon(
    addon_dir: pathlib.Path,
    packages: dict[str, dict],
    icon_url: str | None,
) -> dict:
    manifest = tomllib.loads((addon_dir / "addon.toml").read_text(encoding="utf-8"))
    validate_manifest(manifest, addon_dir)
    capabilities = [item["id"] for item in manifest.get("capabilities", [])]
    addon = {
        "id": manifest["id"],
        "version": manifest["version"],
        "name": manifest["name"],
        "summary": manifest["summary"],
        "license": manifest["license"],
        "source_url": manifest["source_url"],
        "host_version": manifest["host_version"],
        "capabilities": capabilities,
        "dependencies": manifest.get("dependencies", []),
        "permissions": manifest.get("permissions", {}),
        "packages": packages,
    }
    if icon_url is not None:
        icon_path = addon_dir / manifest["icon"]["path"]
        icon_bytes = icon_path.read_bytes()
        addon["icon"] = {
            "url": icon_url,
            "media_type": "png",
            "size": len(icon_bytes),
            "sha256": hashlib.sha256(icon_bytes).hexdigest(),
        }
    return addon


def package_metadata(base_url: str, filename: str, package_path: pathlib.Path) -> dict:
    return {
        "url": f"{base_url}/packages/{filename}",
        "sha256": hashlib.sha256(package_path.read_bytes()).hexdigest(),
        "size": package_path.stat().st_size,
    }


def build(
    root: pathlib.Path,
    output: pathlib.Path,
    sequence: int,
    base_url: str,
    generated: dt.datetime,
    native_artifacts: pathlib.Path | None = None,
) -> None:
    if sequence < 1:
        raise ValueError("sequence must be positive")
    if not base_url.startswith("https://"):
        raise ValueError("base URL must use HTTPS")
    base_url = base_url.rstrip("/")
    if output.exists():
        shutil.rmtree(output)
    packages_dir = output / "packages"
    packages_dir.mkdir(parents=True)
    icons_dir = output / "icons"
    icons_dir.mkdir()

    addons = []
    for addon_dir in sorted((root / "addons").iterdir()):
        if not addon_dir.is_dir() or addon_dir.name.startswith("."):
            continue
        manifest = tomllib.loads((addon_dir / "addon.toml").read_text(encoding="utf-8"))
        validate_manifest(manifest, addon_dir)
        native_entrypoints = {
            rid: entrypoint
            for rid, entrypoint in manifest["entrypoints"].items()
            if entrypoint["kind"] == "native"
        }
        catalog_packages = {}
        if native_entrypoints:
            if native_artifacts is None:
                raise ValueError(f"{addon_dir}: --native-artifacts is required")
            for rid, entrypoint in sorted(manifest["entrypoints"].items()):
                filename = f"{manifest['id']}-{manifest['version']}-{rid}.zip"
                package_path = packages_dir / filename
                native_files = {}
                if entrypoint["kind"] == "native":
                    native_files[entrypoint["path"]] = (
                        native_artifacts / manifest["id"] / entrypoint["path"]
                    )
                write_package(root, addon_dir, package_path, native_files)
                catalog_packages[rid] = package_metadata(base_url, filename, package_path)
        else:
            filename = f"{manifest['id']}-{manifest['version']}.zip"
            package_path = packages_dir / filename
            write_package(root, addon_dir, package_path)
            catalog_packages["any"] = package_metadata(base_url, filename, package_path)
        icon_url = None
        if "icon" in manifest:
            icon_filename = f"{manifest['id']}.png"
            shutil.copyfile(addon_dir / manifest["icon"]["path"], icons_dir / icon_filename)
            icon_url = f"{base_url}/icons/{icon_filename}"
        addons.append(
            catalog_addon(
                addon_dir,
                catalog_packages,
                icon_url,
            )
        )

    index = {
        "schema_version": 2,
        "repository_id": REPOSITORY_ID,
        "repository_name": REPOSITORY_NAME,
        "sequence": sequence,
        "generated_at": rfc3339(generated),
        "expires_at": rfc3339(generated + dt.timedelta(days=21)),
        "addons": addons,
    }
    encoded = json.dumps(index, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8") + b"\n"
    (output / "index-v1.json").write_bytes(encoded)


def main() -> None:
    args = parse_args()
    root = pathlib.Path(__file__).resolve().parents[1]
    build(
        root,
        args.output.resolve(),
        args.sequence,
        args.base_url,
        utc_timestamp(args.generated_at),
        args.native_artifacts.resolve() if args.native_artifacts else None,
    )


if __name__ == "__main__":
    main()
