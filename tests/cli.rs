use assert_cmd::Command;
use std::fs;
use std::path::PathBuf;
use tempfile::TempDir;

struct Fixture {
    _dir: TempDir,
    config_path: PathBuf,
    data_dir: PathBuf,
}

fn fixture() -> Fixture {
    let dir = tempfile::tempdir().expect("tempdir");
    let data_dir = dir.path().join("store");
    let config_path = dir.path().join("config.toml");
    let contents = format!(
        "[app]\nname = \"vecstash\"\n\n\
         [model]\nname = \"Xenova/bge-m3\"\n\n\
         [paths]\ndata_dir = \"{}\"\n\n\
         [runtime]\nmax_batch_size = 4\n",
        data_dir.display()
    );
    fs::write(&config_path, contents).expect("write config");
    Fixture {
        _dir: dir,
        config_path,
        data_dir,
    }
}

fn run(fixture: &Fixture, args: &[&str]) -> assert_cmd::assert::Assert {
    let mut command = Command::cargo_bin("vecstash").expect("binary builds");
    command.arg("--config").arg(&fixture.config_path);
    for arg in args {
        command.arg(arg);
    }
    command.assert()
}

#[test]
fn version_prints_the_crate_version() {
    let mut command = Command::cargo_bin("vecstash").expect("binary builds");
    command
        .arg("version")
        .assert()
        .success()
        .stderr(predicates::str::contains(env!("CARGO_PKG_VERSION")));
}

#[test]
fn version_json_emits_one_compact_line() {
    let mut command = Command::cargo_bin("vecstash").expect("binary builds");
    let output = command.arg("version").arg("--json").output().expect("runs");
    let stdout = String::from_utf8(output.stdout).expect("utf8");
    assert_eq!(
        stdout.lines().count(),
        1,
        "json output must be a single line"
    );
    let parsed: serde_json::Value = serde_json::from_str(stdout.trim()).expect("valid json");
    assert_eq!(parsed["version"], env!("CARGO_PKG_VERSION"));
}

#[test]
fn no_arguments_shows_help_and_fails() {
    let mut command = Command::cargo_bin("vecstash").expect("binary builds");
    command.assert().failure();
}

#[test]
fn status_reports_an_empty_index() {
    let fixture = fixture();
    let output = run(&fixture, &["status", "--json"])
        .success()
        .get_output()
        .stdout
        .clone();
    let parsed: serde_json::Value =
        serde_json::from_slice(&output).expect("status must emit valid json");
    assert_eq!(parsed["documents_count"], 0);
    assert_eq!(parsed["chunks_count"], 0);
    assert_eq!(parsed["vector_dim"], serde_json::Value::Null);
    assert_eq!(parsed["schema_version"], 1);
}

#[test]
fn status_creates_the_config_when_missing() {
    let dir = tempfile::tempdir().expect("tempdir");
    let config_path = dir.path().join("nested").join("config.toml");
    let mut command = Command::cargo_bin("vecstash").expect("binary builds");
    command
        .arg("--config")
        .arg(&config_path)
        .arg("status")
        .arg("--json")
        .assert()
        .success();
    assert!(config_path.exists(), "config must be created on first run");
}

#[test]
fn storage_reports_sizes() {
    let fixture = fixture();
    let output = run(&fixture, &["storage", "--json"])
        .success()
        .get_output()
        .stdout
        .clone();
    let parsed: serde_json::Value = serde_json::from_slice(&output).expect("valid json");
    assert!(parsed["sqlite_path"].is_string());
    assert!(parsed["total_bytes"].is_number());
}

#[test]
fn search_on_empty_index_exits_one() {
    let fixture = fixture();
    run(&fixture, &["search", "anything"]).code(1);
}

#[test]
fn reset_without_force_refuses_and_keeps_the_database() {
    let fixture = fixture();
    run(&fixture, &["status"]).success();
    let db = fixture.data_dir.join("metadata.db");
    assert!(db.exists(), "status must have created the database");

    run(&fixture, &["reset"]).code(1);
    assert!(
        db.exists(),
        "reset without --force must not delete anything"
    );
}

#[test]
fn reset_with_force_deletes_the_database() {
    let fixture = fixture();
    run(&fixture, &["status"]).success();
    let db = fixture.data_dir.join("metadata.db");
    assert!(db.exists());

    run(&fixture, &["reset", "--force"]).success();
    assert!(!db.exists(), "reset --force must delete the database");
}

#[test]
fn reset_on_clean_state_reports_nothing_to_reset() {
    let fixture = fixture();
    run(&fixture, &["status"]).success();
    run(&fixture, &["reset", "--force"]).success();

    let output = run(&fixture, &["reset", "--force", "--json"])
        .success()
        .get_output()
        .stdout
        .clone();
    let parsed: serde_json::Value = serde_json::from_slice(&output).expect("valid json");
    assert_eq!(parsed["status"], "nothing_to_reset");
}

#[test]
fn models_validate_offline_fails_with_code_two() {
    let fixture = fixture();
    let assert = run(
        &fixture,
        &["models", "validate", "--offline-only", "--json"],
    )
    .code(2);
    let parsed: serde_json::Value =
        serde_json::from_slice(&assert.get_output().stdout).expect("valid json");
    assert_eq!(parsed["ok"], false);
    assert!(
        parsed["detail"]
            .as_str()
            .expect("detail is a string")
            .contains("vecstash models bootstrap"),
        "the error must name the fixing command"
    );
}

#[test]
fn models_show_respects_the_json_flag() {
    let fixture = fixture();
    let output = run(&fixture, &["models", "show", "--json"])
        .success()
        .get_output()
        .stdout
        .clone();
    let parsed: serde_json::Value = serde_json::from_slice(&output).expect("valid json");
    assert_eq!(parsed["model_name"], "Xenova/bge-m3");
    assert_eq!(parsed["model_cached"], false);
}

#[test]
fn ingest_rejects_an_unsupported_extension() {
    let fixture = fixture();
    let file = fixture._dir.path().join("data.csv");
    fs::write(&file, "a,b\n1,2\n").expect("write");

    run(&fixture, &["ingest", file.to_str().expect("utf8 path")])
        .code(1)
        .stderr(predicates::str::contains("Unsupported file type"));
}

#[test]
fn ingest_requires_at_least_one_file() {
    let fixture = fixture();
    run(&fixture, &["ingest"]).failure();
}

#[test]
fn config_with_path_outside_data_dir_is_rejected() {
    let dir = tempfile::tempdir().expect("tempdir");
    let config_path = dir.path().join("config.toml");
    fs::write(
        &config_path,
        "[paths]\ndata_dir = \"/tmp/vecstash-a\"\nsqlite_path = \"/tmp/vecstash-b/x.db\"\n",
    )
    .expect("write");

    let mut command = Command::cargo_bin("vecstash").expect("binary builds");
    command
        .arg("--config")
        .arg(&config_path)
        .arg("status")
        .assert()
        .failure()
        .stderr(predicates::str::contains("paths.sqlite_path"));
}

#[test]
fn unknown_execution_provider_is_rejected() {
    let dir = tempfile::tempdir().expect("tempdir");
    let config_path = dir.path().join("config.toml");
    fs::write(&config_path, "[model]\nexecution_provider = \"cuda\"\n").expect("write");

    let mut command = Command::cargo_bin("vecstash").expect("binary builds");
    command
        .arg("--config")
        .arg(&config_path)
        .arg("status")
        .assert()
        .failure()
        .stderr(predicates::str::contains("execution_provider"));
}
