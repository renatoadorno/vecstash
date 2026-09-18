use crate::output::{self, Format};
use anyhow::{Context, Result, anyhow, bail};
use semver::Version;
use serde::Serialize;
use sha2::{Digest, Sha256};
use std::io::Read;
use std::process::ExitCode;

const GITHUB_REPO: &str = "renatoadorno/vecstash";
const ASSET_NAME: &str = "vecstash-aarch64-apple-darwin";
const CHECKSUM_SUFFIX: &str = ".sha256";

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct ReleaseInfo {
    pub current_version: String,
    pub latest_version: String,
    pub update_available: bool,
    pub release_url: String,
    #[serde(skip)]
    pub asset_url: Option<String>,
    #[serde(skip)]
    pub checksum_url: Option<String>,
}

pub fn parse_version(raw: &str) -> Result<Version> {
    let raw = raw.trim();
    let raw = raw.strip_prefix('v').unwrap_or(raw);
    Version::parse(raw).with_context(|| format!("Cannot parse version '{raw}'"))
}

fn find_asset(assets: &serde_json::Value, name: &str) -> Option<String> {
    let assets = assets.as_array()?;
    for asset in assets {
        if asset["name"].as_str() == Some(name) {
            return asset["browser_download_url"].as_str().map(str::to_string);
        }
    }
    None
}

pub fn check_for_update(current: &str) -> Result<ReleaseInfo> {
    let url = format!("https://api.github.com/repos/{GITHUB_REPO}/releases/latest");
    let response = ureq::get(&url)
        .header("Accept", "application/vnd.github+json")
        .header("User-Agent", "vecstash")
        .call();

    let mut response = match response {
        Ok(response) => response,
        Err(ureq::Error::StatusCode(404)) => bail!("No releases found for vecstash."),
        Err(ureq::Error::StatusCode(403)) => bail!("GitHub API rate limit exceeded."),
        Err(ureq::Error::StatusCode(code)) => bail!("GitHub API error: HTTP {code}"),
        Err(e) => bail!("Cannot reach GitHub: {e}"),
    };

    let body: serde_json::Value = response
        .body_mut()
        .read_json()
        .context("GitHub returned a malformed release payload")?;

    let Some(tag) = body["tag_name"].as_str() else {
        bail!("GitHub release has no tag_name.");
    };

    let latest = parse_version(tag)?;
    let current_version = parse_version(current)?;

    Ok(ReleaseInfo {
        current_version: current_version.to_string(),
        latest_version: latest.to_string(),
        update_available: latest > current_version,
        release_url: body["html_url"].as_str().unwrap_or_default().to_string(),
        asset_url: find_asset(&body["assets"], ASSET_NAME),
        checksum_url: find_asset(&body["assets"], &format!("{ASSET_NAME}{CHECKSUM_SUFFIX}")),
    })
}

fn download(url: &str) -> Result<Vec<u8>> {
    let mut response = ureq::get(url)
        .header("User-Agent", "vecstash")
        .call()
        .with_context(|| format!("Cannot download {url}"))?;
    let mut bytes = Vec::new();
    response
        .body_mut()
        .as_reader()
        .read_to_end(&mut bytes)
        .with_context(|| format!("Cannot read the response body from {url}"))?;
    Ok(bytes)
}

pub fn verify_checksum(bytes: &[u8], expected: &str) -> Result<()> {
    let mut hasher = Sha256::new();
    hasher.update(bytes);
    let actual = hex::encode(hasher.finalize());

    let expected = expected.split_whitespace().next().unwrap_or("").trim();
    if expected.is_empty() {
        bail!("The published checksum file is empty.");
    }
    if !actual.eq_ignore_ascii_case(expected) {
        bail!("Checksum mismatch: expected {expected}, got {actual}. Refusing to install.");
    }
    Ok(())
}

fn install(info: &ReleaseInfo) -> Result<()> {
    let Some(asset_url) = info.asset_url.as_deref() else {
        bail!(
            "Release {} has no '{ASSET_NAME}' asset.",
            info.latest_version
        );
    };
    let Some(checksum_url) = info.checksum_url.as_deref() else {
        bail!(
            "Release {} has no '{ASSET_NAME}{CHECKSUM_SUFFIX}' asset. Refusing to install \
             without an integrity check.",
            info.latest_version
        );
    };

    let binary = download(asset_url)?;
    let checksum = download(checksum_url)?;
    let checksum = String::from_utf8(checksum).context("The checksum file is not valid UTF-8")?;
    verify_checksum(&binary, &checksum)?;

    let staged = std::env::temp_dir().join(format!("vecstash-{}", info.latest_version));
    std::fs::write(&staged, &binary)
        .with_context(|| format!("Cannot stage the new binary at {}", staged.display()))?;

    use std::os::unix::fs::PermissionsExt;
    let mut permissions = std::fs::metadata(&staged)?.permissions();
    permissions.set_mode(0o755);
    std::fs::set_permissions(&staged, permissions)?;

    self_replace::self_replace(&staged)
        .map_err(|e| anyhow!("Cannot replace the running binary: {e}"))?;
    let _ = std::fs::remove_file(&staged);
    Ok(())
}

pub fn cmd_update(check: bool, format: Format) -> Result<ExitCode> {
    let info = check_for_update(env!("CARGO_PKG_VERSION"))?;

    if !info.update_available {
        match format {
            Format::Json => output::print_json(&info)?,
            Format::Human => {
                output::print_success(&format!("vecstash {} is up to date.", info.current_version))
            }
        }
        return Ok(ExitCode::SUCCESS);
    }

    if check {
        match format {
            Format::Json => output::print_json(&info)?,
            Format::Human => output::print_line(&format!(
                "Update available: {} -> {}\n{}",
                info.current_version, info.latest_version, info.release_url
            )),
        }
        return Ok(ExitCode::SUCCESS);
    }

    install(&info)?;

    match format {
        Format::Json => output::print_json(&info)?,
        Format::Human => output::print_success(&format!(
            "Updated {} -> {}",
            info.current_version, info.latest_version
        )),
    }
    Ok(ExitCode::SUCCESS)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn version_parses_without_prefix() {
        assert_eq!(
            parse_version("1.2.3").expect("parse"),
            Version::new(1, 2, 3)
        );
    }

    #[test]
    fn version_parses_with_v_prefix() {
        assert_eq!(
            parse_version("v0.2.0").expect("parse"),
            Version::new(0, 2, 0)
        );
    }

    #[test]
    fn prerelease_version_parses_instead_of_failing_silently() {
        let version = parse_version("v1.0.0-rc1").expect("prerelease must parse");
        assert_eq!(version.major, 1);
        assert!(!version.pre.is_empty());
    }

    #[test]
    fn prerelease_sorts_below_release() {
        let pre = parse_version("1.0.0-rc1").expect("parse");
        let release = parse_version("1.0.0").expect("parse");
        assert!(release > pre);
    }

    #[test]
    fn malformed_version_is_reported() {
        let err = parse_version("not-a-version").expect_err("must fail");
        assert!(err.to_string().contains("Cannot parse version"));
    }

    #[test]
    fn newer_version_compares_greater() {
        assert!(parse_version("0.3.0").expect("p") > parse_version("0.2.9").expect("p"));
    }

    #[test]
    fn matching_checksum_is_accepted() {
        let bytes = b"hello world";
        let mut hasher = Sha256::new();
        hasher.update(bytes);
        let digest = hex::encode(hasher.finalize());
        verify_checksum(bytes, &digest).expect("must accept");
    }

    #[test]
    fn checksum_with_filename_suffix_is_accepted() {
        let bytes = b"hello world";
        let mut hasher = Sha256::new();
        hasher.update(bytes);
        let digest = hex::encode(hasher.finalize());
        verify_checksum(bytes, &format!("{digest}  vecstash-aarch64-apple-darwin\n"))
            .expect("must accept the sha256sum output format");
    }

    #[test]
    fn mismatched_checksum_is_rejected() {
        let err = verify_checksum(b"hello world", &"0".repeat(64)).expect_err("must reject");
        assert!(err.to_string().contains("Checksum mismatch"));
    }

    #[test]
    fn empty_checksum_is_rejected() {
        let err = verify_checksum(b"hello world", "   ").expect_err("must reject");
        assert!(err.to_string().contains("empty"));
    }

    #[test]
    fn asset_lookup_finds_the_named_asset() {
        let assets = serde_json::json!([
            { "name": "other", "browser_download_url": "https://example.test/other" },
            { "name": ASSET_NAME, "browser_download_url": "https://example.test/bin" },
        ]);
        assert_eq!(
            find_asset(&assets, ASSET_NAME),
            Some("https://example.test/bin".to_string())
        );
    }

    #[test]
    fn asset_lookup_returns_none_when_absent() {
        let assets = serde_json::json!([]);
        assert_eq!(find_asset(&assets, ASSET_NAME), None);
    }
}
