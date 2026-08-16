use std::collections::BTreeMap;
use std::fs::{self, File};
use std::io::{Read, Write};
use std::path::{Component, Path, PathBuf};
use std::process::Command;

use anyhow::{anyhow, bail, Context, Result};
use chrono::{DateTime, Duration, SecondsFormat, Utc};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use url::Url;
use walkdir::WalkDir;
use zip::write::SimpleFileOptions;
use zip::{CompressionMethod, DateTime as ZipDateTime, ZipWriter};

const REPOSITORY_ID: &str = "org.ersatzrs.addons.official";
const REPOSITORY_NAME: &str = "Official ErsatzRS add-ons";
const MAX_ICON_BYTES: u64 = 2 * 1024 * 1024;
const VALIDITY_DAYS: i64 = 21;

pub struct BuildOptions {
    pub root: PathBuf,
    pub output: PathBuf,
    pub sequence: u64,
    pub base_url: String,
    pub generated_at: DateTime<Utc>,
    pub native_artifacts: Option<PathBuf>,
}

pub trait ContractValidator {
    /// Validate all package manifests before publication work starts.
    ///
    /// # Errors
    ///
    /// Returns an error when the host contract rejects any manifest.
    fn validate_manifests(&self, manifests: &[PathBuf]) -> Result<()>;
    /// Validate the generated unsigned catalog before publication replacement.
    ///
    /// # Errors
    ///
    /// Returns an error when the host contract rejects the catalog.
    fn validate_catalog(&self, catalog: &Path) -> Result<()>;
}

pub struct ProcessValidator {
    executable: PathBuf,
}

impl ProcessValidator {
    #[must_use]
    pub fn new(executable: PathBuf) -> Self {
        Self { executable }
    }

    fn run(&self, args: &[PathBuf]) -> Result<()> {
        let status = Command::new(&self.executable)
            .args(args)
            .status()
            .with_context(|| {
                format!("failed to run host validator {}", self.executable.display())
            })?;
        if !status.success() {
            bail!("host contract validation failed with {status}");
        }
        Ok(())
    }
}

impl ContractValidator for ProcessValidator {
    fn validate_manifests(&self, manifests: &[PathBuf]) -> Result<()> {
        self.run(manifests)
    }

    fn validate_catalog(&self, catalog: &Path) -> Result<()> {
        self.run(&[
            PathBuf::from("--kind"),
            PathBuf::from("catalog"),
            catalog.to_owned(),
        ])
    }
}

#[derive(Debug, Deserialize)]
struct PublicationManifest {
    id: String,
    version: String,
    name: BTreeMap<String, String>,
    summary: BTreeMap<String, String>,
    license: String,
    source_url: String,
    host_version: String,
    #[serde(default)]
    icon: Option<ManifestIcon>,
    #[serde(default)]
    capabilities: Vec<ManifestCapability>,
    #[serde(default)]
    dependencies: Vec<toml::Table>,
    entrypoints: BTreeMap<String, ManifestEntrypoint>,
    #[serde(default)]
    permissions: toml::Table,
}

#[derive(Debug, Deserialize)]
struct ManifestIcon {
    path: String,
    media_type: String,
}

#[derive(Debug, Deserialize)]
struct ManifestCapability {
    id: String,
}

#[derive(Debug, Deserialize)]
struct ManifestEntrypoint {
    path: String,
    kind: String,
}

#[derive(Debug, Serialize)]
struct RepositoryIndex {
    addons: Vec<CatalogAddon>,
    expires_at: String,
    generated_at: String,
    repository_id: &'static str,
    repository_name: &'static str,
    schema_version: u32,
    sequence: u64,
}

#[derive(Debug, Serialize)]
struct CatalogAddon {
    capabilities: Vec<String>,
    dependencies: Vec<toml::Table>,
    host_version: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    icon: Option<CatalogIcon>,
    id: String,
    license: String,
    name: BTreeMap<String, String>,
    packages: BTreeMap<String, CatalogPackage>,
    permissions: toml::Table,
    source_url: String,
    summary: BTreeMap<String, String>,
    version: String,
}

#[derive(Debug, Serialize)]
struct CatalogIcon {
    media_type: String,
    sha256: String,
    size: u64,
    url: String,
}

#[derive(Debug, Serialize)]
struct CatalogPackage {
    sha256: String,
    size: u64,
    url: String,
}

/// Build and atomically replace one unsigned repository publication tree.
///
/// # Errors
///
/// Returns an error without replacing the previous output when validation,
/// package construction, hashing, catalog construction, or staging fails.
pub fn build_repository(options: &BuildOptions, validator: &dyn ContractValidator) -> Result<()> {
    if options.sequence == 0 {
        bail!("sequence must be positive");
    }
    let base_url = validate_base_url(&options.base_url)?;
    let root = options.root.canonicalize().with_context(|| {
        format!(
            "failed to resolve repository root {}",
            options.root.display()
        )
    })?;
    let addon_dirs = addon_directories(&root)?;
    let manifest_paths = addon_dirs
        .iter()
        .map(|directory| directory.join("addon.toml"))
        .collect::<Vec<_>>();
    validator.validate_manifests(&manifest_paths)?;

    let output = absolute_from(&options.output, &std::env::current_dir()?);
    let staging = generated_sibling(&output, "staging")?;
    remove_generated_directory(&staging)?;
    fs::create_dir_all(staging.join("packages"))?;
    fs::create_dir(staging.join("icons"))?;

    let result = build_staged(&root, &staging, &addon_dirs, options, &base_url, validator);
    if let Err(error) = result {
        let _ = remove_generated_directory(&staging);
        return Err(error);
    }
    publish_staging(&staging, &output)
}

fn build_staged(
    root: &Path,
    staging: &Path,
    addon_dirs: &[PathBuf],
    options: &BuildOptions,
    base_url: &str,
    validator: &dyn ContractValidator,
) -> Result<()> {
    let mut addons = Vec::new();
    for addon_dir in addon_dirs {
        let manifest_text = fs::read_to_string(addon_dir.join("addon.toml"))?;
        let manifest: PublicationManifest = toml::from_str(&manifest_text)
            .with_context(|| format!("failed to parse {}", addon_dir.display()))?;
        validate_publication_manifest(&manifest, addon_dir)?;

        let native_entrypoints = manifest
            .entrypoints
            .values()
            .any(|entrypoint| entrypoint.kind == "native");
        let mut packages = BTreeMap::new();
        if native_entrypoints {
            let native_root = options
                .native_artifacts
                .as_deref()
                .context("--native-artifacts is required for native entrypoints")?;
            for (rid, entrypoint) in &manifest.entrypoints {
                let filename = format!("{}-{}-{rid}.zip", manifest.id, manifest.version);
                let destination = staging.join("packages").join(&filename);
                let mut native_files = BTreeMap::new();
                if entrypoint.kind == "native" {
                    native_files.insert(
                        entrypoint.path.clone(),
                        native_root.join(&manifest.id).join(&entrypoint.path),
                    );
                }
                write_package(root, addon_dir, &destination, &native_files)?;
                packages.insert(
                    rid.clone(),
                    package_metadata(base_url, &filename, &destination)?,
                );
            }
        } else {
            let filename = format!("{}-{}.zip", manifest.id, manifest.version);
            let destination = staging.join("packages").join(&filename);
            write_package(root, addon_dir, &destination, &BTreeMap::new())?;
            packages.insert(
                "any".to_owned(),
                package_metadata(base_url, &filename, &destination)?,
            );
        }

        let icon = if let Some(icon) = &manifest.icon {
            let filename = format!("{}.{}", manifest.id, icon.media_type);
            let source = addon_dir.join(&icon.path);
            let destination = staging.join("icons").join(&filename);
            fs::copy(&source, &destination)?;
            Some(CatalogIcon {
                media_type: icon.media_type.clone(),
                sha256: sha256_file(&destination)?,
                size: destination.metadata()?.len(),
                url: format!("{base_url}/icons/{filename}"),
            })
        } else {
            None
        };

        addons.push(CatalogAddon {
            capabilities: manifest
                .capabilities
                .into_iter()
                .map(|capability| capability.id)
                .collect(),
            dependencies: manifest.dependencies,
            host_version: manifest.host_version,
            icon,
            id: manifest.id,
            license: manifest.license,
            name: manifest.name,
            packages,
            permissions: manifest.permissions,
            source_url: manifest.source_url,
            summary: manifest.summary,
            version: manifest.version,
        });
    }

    let index = RepositoryIndex {
        addons,
        expires_at: format_rfc3339(options.generated_at + Duration::days(VALIDITY_DAYS)),
        generated_at: format_rfc3339(options.generated_at),
        repository_id: REPOSITORY_ID,
        repository_name: REPOSITORY_NAME,
        schema_version: 2,
        sequence: options.sequence,
    };
    let mut encoded = serde_json::to_vec(&index)?;
    encoded.push(b'\n');
    let catalog_path = staging.join("index-v1.json");
    fs::write(&catalog_path, encoded)?;
    validator.validate_catalog(&catalog_path)
}

fn validate_base_url(value: &str) -> Result<String> {
    let url = Url::parse(value).context("base URL is invalid")?;
    if url.scheme() != "https"
        || url.host_str().is_none()
        || !url.username().is_empty()
        || url.password().is_some()
        || url.query().is_some()
        || url.fragment().is_some()
    {
        bail!("base URL must be credential-free HTTPS without query or fragment");
    }
    Ok(value.trim_end_matches('/').to_owned())
}

fn addon_directories(root: &Path) -> Result<Vec<PathBuf>> {
    let mut directories = fs::read_dir(root.join("addons"))?
        .filter_map(Result::ok)
        .filter(|entry| {
            entry.file_type().is_ok_and(|kind| kind.is_dir())
                && !entry.file_name().to_string_lossy().starts_with('.')
        })
        .map(|entry| entry.path())
        .collect::<Vec<_>>();
    directories.sort();
    Ok(directories)
}

fn validate_publication_manifest(manifest: &PublicationManifest, addon_dir: &Path) -> Result<()> {
    let directory_name = addon_dir
        .file_name()
        .and_then(|name| name.to_str())
        .context("add-on directory name is not UTF-8")?;
    if manifest.id != directory_name {
        bail!("manifest id must equal package directory name");
    }
    if let Some(icon) = &manifest.icon {
        let source = addon_dir.join(&icon.path);
        let canonical_root = addon_dir.canonicalize()?;
        let canonical_source = source
            .canonicalize()
            .with_context(|| format!("icon {} does not exist", source.display()))?;
        if !canonical_source.starts_with(&canonical_root) || !canonical_source.is_file() {
            bail!("icon must be a regular file inside the add-on directory");
        }
        let bytes = fs::read(&canonical_source)?;
        if bytes.is_empty() || bytes.len() as u64 > MAX_ICON_BYTES {
            bail!("icon must be between 1 byte and 2 MiB");
        }
        match icon.media_type.as_str() {
            "png" if bytes.starts_with(b"\x89PNG\r\n\x1a\n") => {}
            "webp"
                if bytes.len() >= 12 && bytes.starts_with(b"RIFF") && &bytes[8..12] == b"WEBP" => {}
            "png" | "webp" => bail!("icon bytes do not match the declared media type"),
            _ => bail!("unsupported icon media type"),
        }
    }
    Ok(())
}

fn package_files(addon_dir: &Path) -> Result<Vec<PathBuf>> {
    let mut files = Vec::new();
    for entry in WalkDir::new(addon_dir).follow_links(false) {
        let entry = entry?;
        if !entry.file_type().is_file() {
            continue;
        }
        let relative = entry.path().strip_prefix(addon_dir)?;
        if relative.components().any(|component| {
            matches!(component, Component::Normal(value) if value.to_string_lossy().starts_with('.'))
        }) {
            continue;
        }
        files.push(entry.path().to_owned());
    }
    files.sort_by_key(|path| archive_name(path.strip_prefix(addon_dir).expect("walked child")));
    Ok(files)
}

fn write_package(
    root: &Path,
    addon_dir: &Path,
    destination: &Path,
    native_files: &BTreeMap<String, PathBuf>,
) -> Result<()> {
    let file = File::create(destination)?;
    let mut archive = ZipWriter::new(file);
    write_zip_entry(
        &mut archive,
        "LICENSE",
        &fs::read(root.join("LICENSE"))?,
        0o644,
    )?;
    for path in package_files(addon_dir)? {
        let relative = archive_name(path.strip_prefix(addon_dir)?);
        if relative == "LICENSE" {
            continue;
        }
        let mut contents = fs::read(&path)?;
        if path
            .extension()
            .is_some_and(|extension| extension.eq_ignore_ascii_case("bat"))
        {
            contents = normalize_crlf(&contents);
        }
        let mode = if path
            .extension()
            .is_some_and(|extension| extension.eq_ignore_ascii_case("sh"))
        {
            0o755
        } else {
            0o644
        };
        write_zip_entry(&mut archive, &relative, &contents, mode)?;
    }
    for (relative, path) in native_files {
        if !path.is_file() {
            bail!("missing native add-on artifact: {}", path.display());
        }
        write_zip_entry(&mut archive, relative, &fs::read(path)?, 0o755)?;
    }
    archive.finish()?;
    Ok(())
}

fn write_zip_entry(
    archive: &mut ZipWriter<File>,
    name: &str,
    contents: &[u8],
    mode: u32,
) -> Result<()> {
    let timestamp = ZipDateTime::from_date_and_time(2020, 1, 1, 0, 0, 0)
        .map_err(|_| anyhow!("fixed ZIP timestamp is invalid"))?;
    let options = SimpleFileOptions::default()
        .compression_method(CompressionMethod::Deflated)
        .compression_level(Some(9))
        .last_modified_time(timestamp)
        .unix_permissions(mode);
    archive.start_file(name, options)?;
    archive.write_all(contents)?;
    Ok(())
}

fn normalize_crlf(contents: &[u8]) -> Vec<u8> {
    let mut normalized = Vec::with_capacity(contents.len());
    let mut index = 0;
    while index < contents.len() {
        if contents[index] == b'\r' && contents.get(index + 1).is_some_and(|next| *next == b'\n') {
            normalized.extend_from_slice(b"\r\n");
            index += 2;
        } else if contents[index] == b'\n' {
            normalized.extend_from_slice(b"\r\n");
            index += 1;
        } else {
            normalized.push(contents[index]);
            index += 1;
        }
    }
    normalized
}

fn package_metadata(base_url: &str, filename: &str, path: &Path) -> Result<CatalogPackage> {
    Ok(CatalogPackage {
        sha256: sha256_file(path)?,
        size: path.metadata()?.len(),
        url: format!("{base_url}/packages/{filename}"),
    })
}

fn sha256_file(path: &Path) -> Result<String> {
    let mut file = File::open(path)?;
    let mut digest = Sha256::new();
    let mut buffer = vec![0_u8; 64 * 1024].into_boxed_slice();
    loop {
        let read = file.read(&mut buffer)?;
        if read == 0 {
            break;
        }
        digest.update(&buffer[..read]);
    }
    Ok(format!("{:x}", digest.finalize()))
}

fn format_rfc3339(value: DateTime<Utc>) -> String {
    value.to_rfc3339_opts(SecondsFormat::Secs, true)
}

fn archive_name(path: &Path) -> String {
    path.components()
        .filter_map(|component| match component {
            Component::Normal(value) => Some(value.to_string_lossy()),
            _ => None,
        })
        .collect::<Vec<_>>()
        .join("/")
}

fn absolute_from(path: &Path, current_dir: &Path) -> PathBuf {
    if path.is_absolute() {
        path.to_owned()
    } else {
        current_dir.join(path)
    }
}

fn generated_sibling(output: &Path, suffix: &str) -> Result<PathBuf> {
    let parent = output.parent().context("output has no parent directory")?;
    let name = output
        .file_name()
        .and_then(|name| name.to_str())
        .context("output directory name is not UTF-8")?;
    Ok(parent.join(format!(".{name}.{suffix}-{}", std::process::id())))
}

fn remove_generated_directory(path: &Path) -> Result<()> {
    if path.exists() {
        if !path.is_dir() {
            bail!("generated path is not a directory: {}", path.display());
        }
        fs::remove_dir_all(path)?;
    }
    Ok(())
}

fn publish_staging(staging: &Path, output: &Path) -> Result<()> {
    let backup = generated_sibling(output, "previous")?;
    remove_generated_directory(&backup)?;
    let had_output = output.exists();
    if had_output {
        if !output.is_dir() {
            bail!("output path is not a directory: {}", output.display());
        }
        fs::rename(output, &backup)?;
    }
    if let Err(error) = fs::rename(staging, output) {
        if had_output {
            let _ = fs::rename(&backup, output);
        }
        return Err(error.into());
    }
    if had_output {
        remove_generated_directory(&backup)?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;
    use zip::ZipArchive;

    struct AcceptingValidator;

    impl ContractValidator for AcceptingValidator {
        fn validate_manifests(&self, _manifests: &[PathBuf]) -> Result<()> {
            Ok(())
        }

        fn validate_catalog(&self, _catalog: &Path) -> Result<()> {
            Ok(())
        }
    }

    struct RejectingCatalogValidator;

    impl ContractValidator for RejectingCatalogValidator {
        fn validate_manifests(&self, _manifests: &[PathBuf]) -> Result<()> {
            Ok(())
        }

        fn validate_catalog(&self, _catalog: &Path) -> Result<()> {
            bail!("fixture catalog rejection")
        }
    }

    fn repository_root() -> PathBuf {
        Path::new(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .and_then(Path::parent)
            .expect("publisher lives below repository root")
            .to_owned()
    }

    fn options(output: PathBuf) -> BuildOptions {
        BuildOptions {
            root: repository_root(),
            output,
            sequence: 7,
            base_url: "https://example.test/addons".to_owned(),
            generated_at: DateTime::parse_from_rfc3339("2026-08-16T12:00:00Z")
                .expect("timestamp")
                .with_timezone(&Utc),
            native_artifacts: None,
        }
    }

    #[test]
    fn builds_reproducible_packages_catalog_and_crlf_batch_files() {
        let first = TempDir::new().expect("first tempdir");
        let second = TempDir::new().expect("second tempdir");
        let first_output = first.path().join("dist");
        let second_output = second.path().join("dist");
        build_repository(&options(first_output.clone()), &AcceptingValidator).expect("first build");
        build_repository(&options(second_output.clone()), &AcceptingValidator)
            .expect("second build");

        assert_eq!(tree_bytes(&first_output), tree_bytes(&second_output));
        let index: serde_json::Value =
            serde_json::from_slice(&fs::read(first_output.join("index-v1.json")).expect("catalog"))
                .expect("catalog JSON");
        assert_eq!(index["schema_version"], 2);
        assert_eq!(index["repository_id"], REPOSITORY_ID);
        assert_eq!(index["addons"].as_array().expect("add-ons").len(), 2);

        for package in fs::read_dir(first_output.join("packages")).expect("packages") {
            let package = package.expect("package entry").path();
            let mut archive =
                ZipArchive::new(File::open(package).expect("package file")).expect("package ZIP");
            assert!(archive.by_name("LICENSE").is_ok());
            let names = (0..archive.len())
                .map(|index| {
                    archive
                        .by_index(index)
                        .expect("ZIP entry")
                        .name()
                        .to_owned()
                })
                .collect::<Vec<_>>();
            for name in names.into_iter().filter(|name| {
                Path::new(name)
                    .extension()
                    .is_some_and(|extension| extension.eq_ignore_ascii_case("bat"))
            }) {
                let mut contents = Vec::new();
                archive
                    .by_name(&name)
                    .expect("batch entry")
                    .read_to_end(&mut contents)
                    .expect("batch bytes");
                assert!(!contents
                    .windows(2)
                    .any(|pair| pair[1] == b'\n' && pair[0] != b'\r'));
            }
        }
    }

    #[test]
    fn failed_catalog_validation_preserves_the_previous_output() {
        let temporary = TempDir::new().expect("tempdir");
        let output = temporary.path().join("dist");
        fs::create_dir(&output).expect("output");
        fs::write(output.join("sentinel"), b"previous").expect("sentinel");

        let error = build_repository(&options(output.clone()), &RejectingCatalogValidator)
            .expect_err("catalog rejection");
        assert!(error.to_string().contains("fixture catalog rejection"));
        assert_eq!(
            fs::read(output.join("sentinel")).expect("preserved sentinel"),
            b"previous"
        );
    }

    fn tree_bytes(root: &Path) -> BTreeMap<String, Vec<u8>> {
        let mut files = BTreeMap::new();
        for entry in WalkDir::new(root) {
            let entry = entry.expect("tree entry");
            if entry.file_type().is_file() {
                files.insert(
                    archive_name(entry.path().strip_prefix(root).expect("relative path")),
                    fs::read(entry.path()).expect("tree file"),
                );
            }
        }
        files
    }
}
