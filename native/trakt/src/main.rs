use std::env;
use std::fmt::{Display, Formatter};
use std::fs;
use std::io::{self, Write};
use std::process::ExitCode;
use std::time::Duration;

use ersatzrs_addon_contract::{
    AddonCheckResult, AddonCheckStatus, AddonMediaListContentKind, AddonMediaListItemAvailability,
    AddonMediaListItemKind, AddonMediaListRecord, AddonOperationError,
};
use reqwest::blocking::Client;
use reqwest::header::{HeaderMap, ACCEPT};
use reqwest::StatusCode;
use serde::Serialize;
use serde_json::{Map, Value};
use url::Url;

const API_BASE: &str = "https://api.trakt.tv";
const MAX_PAGES: u32 = 100;

#[derive(Debug)]
struct AddonError {
    exit_code: u8,
    code: &'static str,
    message: String,
}

impl AddonError {
    fn new(exit_code: u8, code: &'static str, message: impl Into<String>) -> Self {
        Self {
            exit_code,
            code,
            message: message.into(),
        }
    }
    fn usage(message: impl Into<String>) -> Self {
        Self::new(64, "unsupported-url", message)
    }
    fn unavailable(message: impl Into<String>) -> Self {
        Self::new(69, "provider-unreachable", message)
    }
    fn rejected(message: impl Into<String>) -> Self {
        Self::new(69, "provider-rejected", message)
    }
    fn failed(message: impl Into<String>) -> Self {
        Self::new(70, "operation-failed", message)
    }
}

impl Display for AddonError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        let diagnostic = AddonOperationError::new(self.code, &self.message);
        let json = serde_json::to_string(&diagnostic).map_err(|_| std::fmt::Error)?;
        formatter.write_str(&json)
    }
}

struct ApiResponse {
    body: Value,
    page_count: Option<u32>,
}

trait TraktApi {
    fn get(&self, path: &str) -> Result<ApiResponse, AddonError>;
}

struct HttpTraktApi {
    client: Client,
    client_id: String,
}

impl HttpTraktApi {
    fn new(client_id: String) -> Result<Self, AddonError> {
        let client = Client::builder()
            .timeout(Duration::from_secs(30))
            .user_agent("ErsatzRS-Trakt-Addon/0.2")
            .build()
            .map_err(|error| AddonError::unavailable(format!("HTTP client failed: {error}")))?;
        Ok(Self { client, client_id })
    }
}

impl TraktApi for HttpTraktApi {
    fn get(&self, path: &str) -> Result<ApiResponse, AddonError> {
        let response = self
            .client
            .get(format!("{API_BASE}{path}"))
            .header(ACCEPT, "application/json")
            .header("trakt-api-version", "2")
            .header("trakt-api-key", &self.client_id)
            .send()
            .map_err(|error| {
                AddonError::unavailable(format!("Provider request failed: {error}"))
            })?;
        if !response.status().is_success() {
            let status = response.status();
            let code = if status == StatusCode::TOO_MANY_REQUESTS {
                "provider-rate-limited"
            } else if status == StatusCode::NOT_FOUND {
                "not-found"
            } else {
                "provider-rejected"
            };
            return Err(AddonError::new(
                69,
                code,
                format!("Provider returned HTTP {status}"),
            ));
        }
        let page_count = page_count(response.headers());
        let body = response.json().map_err(|error| {
            AddonError::rejected(format!("Provider returned invalid JSON: {error}"))
        })?;
        Ok(ApiResponse { body, page_count })
    }
}

fn page_count(headers: &HeaderMap) -> Option<u32> {
    headers
        .get("x-pagination-page-count")
        .and_then(|value| value.to_str().ok())
        .and_then(|value| value.parse().ok())
}

fn parse_locator(value: &str) -> Option<(String, String)> {
    let trimmed = value.trim();
    if trimmed.is_empty() {
        return None;
    }
    let segments = if trimmed.contains("://") {
        let parsed = Url::parse(trimmed).ok()?;
        if parsed.scheme() != "https"
            || !matches!(parsed.host_str(), Some("trakt.tv" | "app.trakt.tv"))
        {
            return None;
        }
        parsed
            .path_segments()?
            .filter(|part| !part.is_empty())
            .map(ToOwned::to_owned)
            .collect::<Vec<_>>()
    } else {
        trimmed
            .split('/')
            .filter(|part| !part.is_empty())
            .map(ToOwned::to_owned)
            .collect::<Vec<_>>()
    };
    let (user, slug) = match segments.as_slice() {
        [a, user, c, slug] if a == "users" && c == "lists" => (user, slug),
        [a, user, slug] if a == "users" || a == "lists" => (user, slug),
        [user, b, slug] if b == "lists" => (user, slug),
        [user, slug] => (user, slug),
        _ => return None,
    };
    (valid_slug(user) && valid_slug(slug)).then(|| (user.clone(), slug.clone()))
}

fn valid_slug(value: &str) -> bool {
    !value.is_empty()
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'_' | b'-'))
}

fn client_id() -> String {
    if let Ok(value) = env::var("ERSATZRS_ADDON_SECRET_CLIENT_ID") {
        if !value.trim().is_empty() {
            return value.trim().to_owned();
        }
    }
    env::var("ERSATZRS_ADDON_SECRET_FILE_CLIENT_ID")
        .ok()
        .and_then(|path| fs::read_to_string(path).ok())
        .map(|value| value.trim().to_owned())
        .unwrap_or_default()
}

fn emit(output: &mut impl Write, value: &impl Serialize) -> Result<(), AddonError> {
    serde_json::to_writer(&mut *output, value)
        .map_err(|error| AddonError::failed(format!("JSON output failed: {error}")))?;
    output
        .write_all(b"\n")
        .map_err(|error| AddonError::failed(format!("output failed: {error}")))
}

fn text(value: &Value) -> Option<String> {
    match value {
        Value::String(value) if !value.is_empty() => Some(value.clone()),
        Value::Number(value) => Some(value.to_string()),
        _ => None,
    }
}

fn number(value: Option<&Value>) -> Option<i64> {
    value.and_then(Value::as_i64)
}

fn guid_values(ids: &Map<String, Value>) -> Vec<String> {
    ["imdb", "tmdb", "tvdb"]
        .into_iter()
        .filter_map(|source| text(ids.get(source)?).map(|value| format!("{source}://{value}")))
        .collect()
}

fn project_item(record: &Value, rank: u32) -> Option<AddonMediaListRecord> {
    let record = record.as_object()?;
    let kind = record.get("type")?.as_str()?;
    if !matches!(kind, "movie" | "show" | "season" | "episode") {
        return None;
    }
    let payload = record.get(kind)?.as_object()?;
    let ids = payload.get("ids")?.as_object()?;
    let trakt_id = text(ids.get("trakt")?)?;
    let mut title = payload
        .get("title")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .to_owned();
    let mut year = number(payload.get("year"));
    let mut season = (kind == "season")
        .then(|| number(payload.get("number")))
        .flatten();
    let episode = (kind == "episode")
        .then(|| number(payload.get("number")))
        .flatten();
    if matches!(kind, "season" | "episode") {
        if let Some(show) = record.get("show").and_then(Value::as_object) {
            if let Some(show_title) = show
                .get("title")
                .and_then(Value::as_str)
                .filter(|value| !value.is_empty())
            {
                show_title.clone_into(&mut title);
            }
            year = year.or_else(|| number(show.get("year")));
        }
    }
    if title.is_empty() {
        let label = match kind {
            "movie" => "Movie",
            "show" => "Show",
            "season" => "Season",
            "episode" => "Episode",
            _ => return None,
        };
        title = format!("{label} {trakt_id}");
    }
    if kind == "episode" {
        season = number(payload.get("season"));
    }
    let display_title = match kind {
        "season" if season.is_some() => format!("{title} - Season {}", season.unwrap_or_default()),
        "episode" if episode.is_some() => format!(
            "{title} - S{:02}E{:02}",
            season.unwrap_or_default(),
            episode.unwrap_or_default()
        ),
        _ if year.is_some() => format!("{title} ({})", year.unwrap_or_default()),
        _ => title.clone(),
    };
    let wire_kind = match kind {
        "movie" => AddonMediaListItemKind::Movie,
        "show" => AddonMediaListItemKind::Show,
        "season" => AddonMediaListItemKind::Season,
        "episode" => AddonMediaListItemKind::Episode,
        _ => return None,
    };
    Some(AddonMediaListRecord::Item {
        provider_id: format!("{kind}:{trakt_id}"),
        rank: i32::try_from(rank).ok()?,
        display_title,
        title,
        year: year.and_then(|value| i32::try_from(value).ok()),
        season: season.and_then(|value| i32::try_from(value).ok()),
        episode: episode.and_then(|value| i32::try_from(value).ok()),
        kind: wire_kind,
        guids: guid_values(ids),
        source_url: None,
        availability: AddonMediaListItemAvailability::Available,
        availability_reason: None,
        content_kind: AddonMediaListContentKind::Auto,
    })
}

fn list_operation(
    api: &impl TraktApi,
    source: &str,
    output: &mut impl Write,
) -> Result<(), AddonError> {
    let (user, slug) = parse_locator(source)
        .ok_or_else(|| AddonError::usage("unsupported public Trakt list URL"))?;
    let prefix = if user.eq_ignore_ascii_case("official") {
        format!("/lists/{slug}")
    } else {
        format!("/users/{user}/lists/{slug}")
    };
    let metadata = api.get(&prefix)?.body;
    let metadata = metadata
        .as_object()
        .ok_or_else(|| AddonError::rejected("Provider list metadata response is invalid"))?;
    let provider_id = metadata
        .get("ids")
        .and_then(Value::as_object)
        .and_then(|ids| ids.get("trakt"))
        .and_then(text)
        .unwrap_or_else(|| format!("{user}/{slug}"));
    emit(
        output,
        &AddonMediaListRecord::List {
            provider_id,
            name: metadata
                .get("name")
                .and_then(Value::as_str)
                .filter(|value| !value.is_empty())
                .unwrap_or(&slug)
                .to_owned(),
            description: metadata
                .get("description")
                .and_then(Value::as_str)
                .map(ToOwned::to_owned),
        },
    )?;
    let mut rank = 0_u32;
    for page in 1..=MAX_PAGES {
        let response = api.get(&format!(
            "{prefix}/items?extended=full&limit=100&page={page}"
        ))?;
        let records = response
            .body
            .as_array()
            .ok_or_else(|| AddonError::rejected("Provider list-items response is invalid"))?;
        for record in records {
            if let Some(item) = project_item(record, rank) {
                emit(output, &item)?;
                rank = rank.saturating_add(1);
            }
        }
        if records.is_empty() || page >= response.page_count.unwrap_or(page) {
            break;
        }
    }
    Ok(())
}

fn check_result(configured: bool) -> AddonCheckResult {
    if configured {
        AddonCheckResult {
            status: AddonCheckStatus::Ready,
            code: "ready".to_owned(),
            message: "Trakt Lists is ready.".to_owned(),
        }
    } else {
        AddonCheckResult {
            status: AddonCheckStatus::Unavailable,
            code: "missing-client-id-reference".to_owned(),
            message: "Configure the client ID as a secret reference.".to_owned(),
        }
    }
}

fn run() -> Result<(), AddonError> {
    let operation = env::args().nth(1).unwrap_or_default();
    let secret = client_id();
    let stdout = io::stdout();
    let mut output = stdout.lock();
    match operation.as_str() {
        "check" => {
            let result = check_result(!secret.is_empty());
            emit(&mut output, &result)
        }
        "list" if secret.is_empty() => Err(AddonError::new(
            78,
            "missing-secret",
            "Required add-on secret reference is not configured",
        )),
        "list" => list_operation(
            &HttpTraktApi::new(secret)?,
            &env::var("ERSATZRS_MEDIA_LIST_URL").unwrap_or_default(),
            &mut output,
        ),
        _ => Err(AddonError::failed("Unsupported add-on operation")),
    }
}

fn main() -> ExitCode {
    match run() {
        Ok(()) => ExitCode::SUCCESS,
        Err(error) => {
            eprintln!("{error}");
            ExitCode::from(error.exit_code)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    use std::cell::RefCell;
    use std::collections::VecDeque;

    struct FakeApi {
        paths: RefCell<Vec<String>>,
        responses: RefCell<VecDeque<ApiResponse>>,
    }
    impl FakeApi {
        fn new(responses: Vec<ApiResponse>) -> Self {
            Self {
                paths: RefCell::new(Vec::new()),
                responses: RefCell::new(responses.into()),
            }
        }
    }
    impl TraktApi for FakeApi {
        fn get(&self, path: &str) -> Result<ApiResponse, AddonError> {
            self.paths.borrow_mut().push(path.to_owned());
            self.responses
                .borrow_mut()
                .pop_front()
                .ok_or_else(|| AddonError::unavailable("missing fake response"))
        }
    }

    #[test]
    fn preserves_locator_forms() {
        for value in [
            "https://trakt.tv/users/u/lists/l",
            "https://app.trakt.tv/users/u/l",
            "https://trakt.tv/lists/u/l",
            "u/lists/l",
            "u/l",
        ] {
            assert_eq!(parse_locator(value), Some(("u".to_owned(), "l".to_owned())));
        }
        assert_eq!(
            parse_locator("https://example.invalid/users/u/lists/l"),
            None
        );
        assert_eq!(
            parse_locator("https://trakt.tv/users/u/lists/l/extra"),
            None
        );
    }

    #[test]
    fn readiness_depends_only_on_the_secret_reference() {
        assert_eq!(check_result(true).status, AddonCheckStatus::Ready);
        assert_eq!(check_result(false).code, "missing-client-id-reference");
    }

    #[test]
    fn failures_render_as_structured_operation_diagnostics() {
        let error = AddonError::new(78, "missing-secret", "Secret is unavailable");
        let payload: Value = serde_json::from_str(&error.to_string()).unwrap();
        assert_eq!(payload["code"], "missing-secret");
        assert_eq!(payload["message"], "Secret is unavailable");
    }

    #[test]
    fn projects_guids_and_skips_unknown_kinds() {
        let item = project_item(&json!({"type":"movie","movie":{"title":"Movie","year":1999,"ids":{"trakt":10,"imdb":"tt1","tmdb":20,"tvdb":30}}}), 0).unwrap();
        let AddonMediaListRecord::Item { guids, .. } = item else {
            panic!("expected item record");
        };
        assert_eq!(guids, ["imdb://tt1", "tmdb://20", "tvdb://30"]);
        assert_eq!(
            project_item(&json!({"type":"person","person":{"ids":{"trakt":1}}}), 0),
            None
        );
    }

    #[test]
    fn emits_paginated_list_records() {
        let api = FakeApi::new(vec![
            ApiResponse {
                body: json!({"name":"List","ids":{"trakt":42}}),
                page_count: None,
            },
            ApiResponse {
                body: json!([{"type":"movie","movie":{"title":"Movie","ids":{"trakt":10,"imdb":"tt1"}}}]),
                page_count: Some(2),
            },
            ApiResponse {
                body: json!([{"type":"episode","episode":{"season":3,"number":4,"ids":{"trakt":11}},"show":{"title":"Show"}}]),
                page_count: Some(2),
            },
        ]);
        let mut output = Vec::new();
        list_operation(&api, "https://trakt.tv/users/u/lists/l", &mut output).unwrap();
        ersatzrs_addon_contract::conform_media_list_output(&output)
            .expect("shared media-list contract");
        let rows = String::from_utf8(output)
            .unwrap()
            .lines()
            .map(|line| serde_json::from_str::<Value>(line).unwrap())
            .collect::<Vec<_>>();
        assert_eq!(rows[0]["provider_id"], "42");
        assert_eq!(rows[1]["guids"], json!(["imdb://tt1"]));
        assert!(rows[1].get("availability").is_none());
        assert!(rows[1].get("content_kind").is_none());
        assert!(rows[1].get("source_url").is_none());
        assert_eq!(rows[2]["rank"], 1);
        assert_eq!(api.paths.into_inner().len(), 3);
    }
}
