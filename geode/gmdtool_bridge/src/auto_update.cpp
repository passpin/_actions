// GitHub Releases updater for the Windows gmdtool Runtime Bridge.
// Does not patch the running DLL. Only the .geode package is staged and
// (upon explicit restart approval) atomically swapped with rollback.
#include <Geode/Geode.hpp>
#include <Geode/DefaultInclude.hpp>
#include <Geode/binding/MenuLayer.hpp>
#include <Geode/modify/MenuLayer.hpp>
#include <Geode/ui/Popup.hpp>
#include <Geode/utils/web.hpp>
#include <Geode/utils/file.hpp>
#include <Geode/utils/general.hpp>
#include <matjson.hpp>

#ifdef GEODE_IS_WINDOWS
#include <bcrypt.h>
#include <algorithm>
#include <array>
#include <chrono>
#include <cctype>
#include <cstdint>
#include <filesystem>
#include <optional>
#include <sstream>
#include <string>
#include <tuple>
#include <vector>

using namespace geode::prelude;
namespace {
namespace fs = std::filesystem;
namespace web = geode::utils::web;

constexpr auto API_URL = "https://api.github.com/repos/passpin/for_build/releases/latest";
constexpr auto ASSET_NAME = "gmdtool.runtime-bridge.geode";
constexpr auto ASSET_BASE = "https://github.com/passpin/for_build/releases/download/";
constexpr auto MOD_ID = "gmdtool.runtime-bridge";
constexpr std::size_t MAX_BYTES = 32 * 1024 * 1024;
constexpr std::size_t MIN_BYTES = 1024;
// An open main menu checks for new releases again without restarting GD.
// The menu polls cheaply every 30 seconds; at most one GitHub API request
// is made every five minutes while it is open.
constexpr auto CHECK_INTERVAL = std::chrono::minutes(5);
constexpr auto PROMPT_SNOOZE = std::chrono::minutes(10);

// Return only canonical stable semvers: we explicitly do not install prereleases.
std::optional<std::array<int, 3>> parseVersion(std::string s) {
    if (!s.empty() && s[0] == 'v') s.erase(0, 1);
    std::array<int, 3> parts{};
    std::size_t start = 0;
    for (int i = 0; i < 3; ++i) {
        auto end = s.find('.', start);
        if (i < 2 && end == std::string::npos) return std::nullopt;
        if (i == 2) end = s.size();
        if (end == start || end - start > 5) return std::nullopt;
        int value = 0;
        for (auto j = start; j < end; ++j) {
            if (!std::isdigit(static_cast<unsigned char>(s[j]))) return std::nullopt;
            value = value * 10 + (s[j] - '0');
        }
        parts[i] = value;
        if (i < 2) start = end + 1;
    }
    return parts;
}

std::string sha256(geode::ByteVector const& data) {
    // Windows CNG, with the provider owned only for this short operation.
    BCRYPT_ALG_HANDLE alg = nullptr;
    if (!BCRYPT_SUCCESS(BCryptOpenAlgorithmProvider(&alg, BCRYPT_SHA256_ALGORITHM, nullptr, 0))) return {};
    std::array<unsigned char, 32> bytes{};
    auto result = BCryptHash(alg, nullptr, 0,
        reinterpret_cast<PUCHAR>(const_cast<geode::ByteVector::value_type*>(data.data())),
        static_cast<ULONG>(data.size()), bytes.data(), static_cast<ULONG>(bytes.size()));
    BCryptCloseAlgorithmProvider(alg, 0);
    if (!BCRYPT_SUCCESS(result)) return {};
    constexpr char digits[] = "0123456789abcdef";
    std::string out;
    out.reserve(64);
    for (auto b : bytes) { out += digits[b >> 4]; out += digits[b & 0xf]; }
    return out;
}

struct Release {
    std::string version;
    std::string url;
    std::string digest;
    std::size_t size = 0;
};

std::optional<Release> parseRelease(matjson::Value const& json) {
    if (json["draft"].asBool().unwrapOr(true) ||
        json["prerelease"].asBool().unwrapOr(true)) return std::nullopt;
    auto version = json["tag_name"].asString().unwrapOr("");
    auto remote = parseVersion(version);
    auto local = parseVersion(Mod::get()->getVersion().toVString(false));
    if (!remote || !local || *remote <= *local) return std::nullopt;

    auto assets = json["assets"].asArray();
    if (!assets) return std::nullopt;
    for (auto const& a : assets.unwrap()) {
        if (a["name"].asString().unwrapOr("") != ASSET_NAME) continue;
        auto url = a["browser_download_url"].asString().unwrapOr("");
        auto digest = a["digest"].asString().unwrapOr("");
        auto size = a["size"].asInt().unwrapOr(0);
        // For safety we require GitHub's SHA256 release-asset digest.
        if (url.starts_with(ASSET_BASE) &&
            url.find_first_of("\r\n\t\\?#") == std::string::npos &&
            digest.starts_with("sha256:") && digest.size() == 71 &&
            size >= static_cast<std::int64_t>(MIN_BYTES) &&
            size <= static_cast<std::int64_t>(MAX_BYTES)) {
            auto hex = digest.substr(7);
            if (!std::all_of(hex.begin(), hex.end(), [](char c) {
                return (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f') || (c >= 'A' && c <= 'F');
            })) continue;
            std::transform(hex.begin(), hex.end(), hex.begin(), [](char c) {
                return static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
            });
            return Release{version, url, hex, static_cast<std::size_t>(size)};
        }
    }
    return std::nullopt;
}

// Inspect metadata before installing an untrusted downloaded archive.
bool inspectPackage(fs::path const& staged, std::string const& version) {
    auto opened = geode::utils::file::Unzip::create(staged);
    if (!opened) return false;
    auto manifest = opened.unwrap().extract("mod.json");
    if (!manifest || manifest.unwrap().size() > 128 * 1024) return false;
    auto const& bytes = manifest.unwrap();
    auto json = matjson::parse(std::string(bytes.begin(), bytes.end()));
    if (!json) return false;
    auto const& meta = json.unwrap();
    return meta["id"].asString().unwrapOr("") == MOD_ID &&
        meta["version"].asString().unwrapOr("") == version &&
        meta["gd"]["win"].asString().unwrapOr("") == "2.2081" &&
        meta["geode"].asString().unwrapOr("") == "5.9.0";
}

class Updater {
    geode::async::TaskHolder<web::WebResponse> m_check;
    geode::async::TaskHolder<web::WebResponse> m_download;
    bool m_checking = false;
    bool m_busy = false;
    bool m_prompted = false;
    std::chrono::steady_clock::time_point m_lastCheck{};
    std::chrono::steady_clock::time_point m_promptAfter{};
    std::optional<Release> m_release;
    fs::path m_staged;

    bool isMainMenuActive() const {
        auto* scene = cocos2d::CCDirector::sharedDirector()->getRunningScene();
        return scene && scene->getChildByType<MenuLayer>(0) != nullptr;
    }

    void showRestartPrompt() {
        if (m_prompted || !m_release || m_staged.empty() || !fs::exists(m_staged)) return;
        // Don't interrupt a level if the asynchronous download finished after
        // the player left the menu; the prompt appears on returning to it.
        if (!isMainMenuActive()) return;
        if (std::chrono::steady_clock::now() < m_promptAfter) return;
        m_prompted = true;
        // One short line; do not include a literal \n or force manual wrapping.
        auto text = fmt::format("{} ready. Restart?", m_release->version);
        geode::createQuickPopup("gmdtool Update", text, "Later", "Restart", [this](auto, bool yes) {
            if (!yes) {
                m_prompted = false;
                m_promptAfter = std::chrono::steady_clock::now() + PROMPT_SNOOZE;
                return;
            }
            if (!this->apply()) {
                m_prompted = false;
                m_promptAfter = std::chrono::steady_clock::now() + PROMPT_SNOOZE;
                FLAlertLayer::create("Update failed",
                    "Original mod kept. See Geode logs.", "OK")->show();
                return;
            }
            geode::utils::game::restart(true, false);
        });
    }

    bool apply() {
        // File operation only; no DLL unload or hot-reload. If the package is
        // locked by the OS, the rename fails and the original is kept.
        if (!m_release || m_staged.empty() || !fs::exists(m_staged)) return false;
        auto current = Mod::get()->getPackagePath();
        if (current.extension() != ".geode" || !fs::is_regular_file(current)) return false;
        if (!inspectPackage(m_staged, m_release->version)) return false;
        // The backup is NOT inside the mods directory, so the loader will not
        // mistake it for another installed package.
        auto backup = Mod::get()->getSaveDir() / "previous-version.geode.backup";
        std::error_code ec;
        fs::copy_file(current, backup, fs::copy_options::overwrite_existing, ec);
        if (ec) { log::error("Updater: backup failed: {}", ec.message()); return false; }
        fs::rename(current, current.string() + ".old-staging", ec);
        if (ec) { log::error("Updater: cannot rename current mod: {}", ec.message()); return false; }
        auto old = fs::path(current.string() + ".old-staging");
        fs::rename(m_staged, current, ec);
        if (ec) {
            log::error("Updater: cannot install new mod: {}", ec.message());
            std::error_code restore;
            fs::rename(old, current, restore);
            if (restore) log::error("Updater: rollback failed; backup at {}", backup.string());
            return false;
        }
        std::error_code removeError;
        fs::remove(old, removeError);
        if (removeError) log::warn("Updater: old package remains as {}", old.string());
        m_staged.clear();
        return true;
    }

public:
    void onMenu() {
        if (!Mod::get()->getSettingValue<bool>("auto-update")) return;
        if (!m_staged.empty() && fs::exists(m_staged)) {
            geode::queueInMainThread([this] { this->showRestartPrompt(); });
            return;
        }
        if (m_checking || m_busy) return;
        auto now = std::chrono::steady_clock::now();
        if (m_lastCheck.time_since_epoch().count() != 0 &&
            now - m_lastCheck < CHECK_INTERVAL) return;
        m_lastCheck = now;
        m_checking = true;
        auto req = web::WebRequest();
        req.userAgent("gmdtool-runtime-bridge/passpin")
            .header("Accept", "application/vnd.github+json")
            .timeout(std::chrono::seconds(15));
        m_check.spawn(req.get(API_URL), [this](web::WebResponse response) {
            m_checking = false;
            if (!response.ok() || response.data().size() > 1024 * 1024) {
                log::warn("Updater: GitHub release check failed (HTTP {})", response.code());
                return;
            }
            auto parsed = response.json();
            if (!parsed) { log::warn("Updater: response was not JSON"); return; }
            auto release = parseRelease(parsed.unwrap());
            if (!release) { log::info("Updater: no supported newer release"); return; }
            m_release = std::move(release);
            m_busy = true;
            auto download = web::WebRequest();
            download.userAgent("gmdtool-runtime-bridge/passpin")
                .timeout(std::chrono::seconds(90));
            m_download.spawn(download.get(m_release->url), [this](web::WebResponse body) {
                m_busy = false;
                if (!m_release || !body.ok() || body.data().size() != m_release->size ||
                    body.data().size() > MAX_BYTES) {
                    log::error("Updater: download failed or size mismatch"); return;
                }
                if (sha256(body.data()) != m_release->digest) {
                    log::error("Updater: SHA256 mismatch; update rejected"); return;
                }
                auto staged = Mod::get()->getSaveDir() / "update-staged.geode.part";
                auto written = geode::utils::file::writeBinarySafe(staged, body.data());
                if (!written || !inspectPackage(staged, m_release->version)) {
                    std::error_code ignored;
                    fs::remove(staged, ignored);
                    log::error("Updater: package write or metadata validation failed");
                    return;
                }
                m_staged = std::move(staged);
                log::info("Updater: {} verified and staged", m_release->version);
                this->showRestartPrompt();
            });
        });
    }
};

Updater& updater() { static Updater u; return u; }
class $modify(GmdtoolUpdateMenuLayer, MenuLayer) {
    void pollForUpdates(float) {
        updater().onMenu();
    }

    bool init() {
        if (!MenuLayer::init()) return false;
        // The original one-shot check meant GD had to be restarted to detect
        // releases published after menu creation. Re-check while it is open.
        this->schedule(schedule_selector(GmdtoolUpdateMenuLayer::pollForUpdates), 30.0f);
        geode::queueInMainThread([] { updater().onMenu(); });
        return true;
    }
};
} // namespace
#endif
