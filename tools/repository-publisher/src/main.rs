use std::path::PathBuf;

use anyhow::{bail, Context, Result};
use chrono::{DateTime, Timelike, Utc};
use repository_publisher::{build_repository, BuildOptions, ProcessValidator};

fn main() -> Result<()> {
    let args = std::env::args().skip(1).collect::<Vec<_>>();
    let options = parse_args(&args)?;
    let validator = ProcessValidator::new(options.validator);
    build_repository(
        &BuildOptions {
            root: options.root,
            output: options.output,
            sequence: options.sequence,
            base_url: options.base_url,
            generated_at: options.generated_at,
            native_artifacts: options.native_artifacts,
        },
        &validator,
    )
}

struct CliOptions {
    root: PathBuf,
    output: PathBuf,
    sequence: u64,
    base_url: String,
    generated_at: DateTime<Utc>,
    native_artifacts: Option<PathBuf>,
    validator: PathBuf,
}

fn parse_args(args: &[String]) -> Result<CliOptions> {
    if args
        .iter()
        .any(|arg| matches!(arg.as_str(), "-h" | "--help"))
    {
        print_help();
        std::process::exit(0);
    }

    let mut root = PathBuf::from(".");
    let mut output = None;
    let mut sequence = None;
    let mut base_url = None;
    let mut generated_at = None;
    let mut native_artifacts = None;
    let mut validator = None;
    let mut index = 0;
    while index < args.len() {
        let flag = &args[index];
        let value = args
            .get(index + 1)
            .with_context(|| format!("{flag} requires a value"))?;
        match flag.as_str() {
            "--root" => root = PathBuf::from(value),
            "--output" => output = Some(PathBuf::from(value)),
            "--sequence" => sequence = Some(value.parse().context("invalid --sequence")?),
            "--base-url" => base_url = Some(value.clone()),
            "--generated-at" => {
                generated_at = Some(
                    DateTime::parse_from_rfc3339(value)
                        .context("invalid --generated-at")?
                        .with_timezone(&Utc),
                );
            }
            "--native-artifacts" => native_artifacts = Some(PathBuf::from(value)),
            "--validator" => validator = Some(PathBuf::from(value)),
            _ => bail!("unknown option `{flag}`"),
        }
        index += 2;
    }

    Ok(CliOptions {
        root,
        output: output.context("--output is required")?,
        sequence: sequence.context("--sequence is required")?,
        base_url: base_url.context("--base-url is required")?,
        generated_at: generated_at.unwrap_or_else(|| {
            Utc::now()
                .with_nanosecond(0)
                .expect("zero nanoseconds are valid")
        }),
        native_artifacts,
        validator: validator.context("--validator is required")?,
    })
}

fn print_help() {
    eprintln!("repository-publisher — build the unsigned official add-on repository");
    eprintln!();
    eprintln!("USAGE:");
    eprintln!("    repository-publisher --sequence <N> --base-url <HTTPS_URL> --output <DIR> --validator <PATH> [OPTIONS]");
    eprintln!();
    eprintln!("OPTIONS:");
    eprintln!("    --root <DIR>                 Repository root (default: current directory)");
    eprintln!("    --generated-at <RFC3339>     Fixed generation time for reproducible builds");
    eprintln!("    --native-artifacts <DIR>     Root containing optional native RID artifacts");
}
