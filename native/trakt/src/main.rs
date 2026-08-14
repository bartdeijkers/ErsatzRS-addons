use std::env;
use std::fmt::{Display, Formatter};
use std::fs;
use std::io::{self, Write};
use std::process::ExitCode;
use std::time::Duration;

use reqwest::blocking::Client;
use reqwest::header::{HeaderMap, ACCEPT};
use serde_json::{json, Map, Value};
use url::Url;

const API_BASE: &str = "https://api.trakt.tv";
const MAX_PAGES: u32 = 100;

#[derive(Debug)]
struct AddonError {
    exit_code: u8,
    message: String,
}

impl AddonError {
    fn new(exit_code: u8, message: impl Into<String>) -> Self {
        Self {
            exit_code,
            message: message.into(),
        }
    }
    fn usage(message: impl Into<String>) -> Self {
        Self::new(64, message)
    }
    fn unavailable(message: impl Into<String>) -> Self {
        Self::new(69, message)
    }
}

impl Display for AddonError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(&self.message)
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
            .and_then(reqwest::blocking::Response::error_for_status)
            .map_err(|error| {
                AddonError::unavailable(format!("Trakt HTTP request failed: {error}"))
            })?;
        let page_count = page_count(response.headers());
        let body = response.json().map_err(|error| {
            AddonError::unavailable(format!("Trakt JSON response failed: {error}"))
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

fn emit(output: &mut impl Write, value: &Value) -> Result<(), AddonError> {
    serde_json::to_writer(&mut *output, value)
        .map_err(|error| AddonError::unavailable(format!("JSON output failed: {error}")))?;
    output
        .write_all(b"\n")
        .map_err(|error| AddonError::unavailable(format!("output failed: {error}")))
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

fn project_item(record: &Value, rank: u32) -> Option<Value> {
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
    let mut item = Map::from_iter([
        ("record_type".to_owned(), json!("item")),
        (
            "provider_id".to_owned(),
            json!(format!("{kind}:{trakt_id}")),
        ),
        ("rank".to_owned(), json!(rank)),
        ("display_title".to_owned(), json!(display_title)),
        ("title".to_owned(), json!(title)),
        ("kind".to_owned(), json!(kind)),
        ("guids".to_owned(), json!(guid_values(ids))),
    ]);
    if let Some(value) = year {
        item.insert("year".to_owned(), json!(value));
    }
    if let Some(value) = season {
        item.insert("season".to_owned(), json!(value));
    }
    if let Some(value) = episode {
        item.insert("episode".to_owned(), json!(value));
    }
    Some(Value::Object(item))
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
        .ok_or_else(|| AddonError::unavailable("Trakt list metadata response is invalid"))?;
    let provider_id = metadata
        .get("ids")
        .and_then(Value::as_object)
        .and_then(|ids| ids.get("trakt"))
        .and_then(text)
        .unwrap_or_else(|| format!("{user}/{slug}"));
    emit(
        output,
        &json!({
            "record_type":"list", "provider_id":provider_id,
            "name":metadata.get("name").and_then(Value::as_str).filter(|value| !value.is_empty()).unwrap_or(&slug),
            "description":metadata.get("description").unwrap_or(&Value::Null)
        }),
    )?;
    let mut rank = 0_u32;
    for page in 1..=MAX_PAGES {
        let response = api.get(&format!(
            "{prefix}/items?extended=full&limit=100&page={page}"
        ))?;
        let records = response
            .body
            .as_array()
            .ok_or_else(|| AddonError::unavailable("Trakt list-items response is invalid"))?;
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

fn check_result(configured: bool) -> Value {
    if configured {
        json!({"status":"ready","code":"ready","message":"Trakt Lists is ready."})
    } else {
        json!({"status":"unavailable","code":"missing-client-id-reference","message":"Configure the client ID as a secret reference."})
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
            "Trakt client ID reference is not configured",
        )),
        "list" => list_operation(
            &HttpTraktApi::new(secret)?,
            &env::var("ERSATZRS_MEDIA_LIST_URL").unwrap_or_default(),
            &mut output,
        ),
        _ => Err(AddonError::usage("unsupported add-on operation")),
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
        assert_eq!(check_result(true)["status"], "ready");
        assert_eq!(check_result(false)["code"], "missing-client-id-reference");
    }

    #[test]
    fn projects_guids_and_skips_unknown_kinds() {
        let item = project_item(&json!({"type":"movie","movie":{"title":"Movie","year":1999,"ids":{"trakt":10,"imdb":"tt1","tmdb":20,"tvdb":30}}}), 0).unwrap();
        assert_eq!(
            item["guids"],
            json!(["imdb://tt1", "tmdb://20", "tvdb://30"])
        );
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
        let rows = String::from_utf8(output)
            .unwrap()
            .lines()
            .map(|line| serde_json::from_str::<Value>(line).unwrap())
            .collect::<Vec<_>>();
        assert_eq!(rows[0]["provider_id"], "42");
        assert_eq!(rows[1]["guids"], json!(["imdb://tt1"]));
        assert_eq!(rows[2]["rank"], 1);
        assert_eq!(api.paths.into_inner().len(), 3);
    }
}
