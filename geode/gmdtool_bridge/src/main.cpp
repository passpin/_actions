// Windows-first experimental Geometry Dash bridge.
// All GD objects and Cocos state are accessed on the game main thread only.
#include <Geode/Geode.hpp>
#include <Geode/DefaultInclude.hpp>
#include <Geode/binding/PlayLayer.hpp>
#include <Geode/binding/MenuLayer.hpp>
#include <Geode/modify/MenuLayer.hpp>
#include <Geode/modify/PlayLayer.hpp>
#include <Geode/binding/PlayerObject.hpp>
#include <Geode/binding/GJEffectManager.hpp>
#include <matjson.hpp>
#include "bridge_transport.hpp"
#include <algorithm>
#include <atomic>
#include <exception>
#include <cstdint>
#include <vector>
#include <chrono>
#include <filesystem>
#include <future>
#include <iomanip>
#include <random>
#include <sstream>
#include <string>
#include <thread>
#include <memory>
#include <mutex>
#include <deque>
#include <functional>
#include <Windows.h> // Win32 window/message queries only; Winsock remains in bridge_transport.cpp
#include <commctrl.h> // Windows supported subclassing; hooks on the UI/game thread

using namespace geode::prelude;

#ifdef GEODE_IS_WINDOWS
namespace {
constexpr int PORT = 18731;

// These counters are safe to read from the network thread. They carry NO
// Geometry Dash or Cocos pointers and do not infer game-thread responsiveness
// from transport connectivity.
struct DispatchCounters {
    std::atomic<std::uint64_t> queued{0};
    std::atomic<std::uint64_t> started{0};
    std::atomic<std::uint64_t> completed{0};
    std::atomic<std::uint64_t> timedOut{0};
    std::atomic<std::int64_t> lastCompletedMs{0};
    std::atomic<std::int64_t> lastPostUpdateMs{0};
    std::atomic<std::uint64_t> postUpdates{0};
};
DispatchCounters counters;


// Background play is experimental and opt-in TWICE: Geode setting + authenticated
// RPC switch. Keep the decision on the UI thread; network thread only sends JSON.
// Crucially, this does not restart a minimized renderer or synthesize frames.
std::atomic_bool backgroundPlayRequested{false};
std::atomic<std::uint64_t> unfocusPauseRequests{0};
std::atomic<std::uint64_t> unfocusPauseSuppressed{0};
// A non-unfocus pause may come from the user OR another mod. Never bypass it.
std::atomic<std::uint64_t> nonUnfocusPauseRequests{0};

// A SECOND, independent pause mechanism may pause Cocos's Director when the
// Win32 window deactivates, even when PlayLayer::pauseGame(true) was bypassed.
// This recovery experiment runs ONLY on the already-verified game/UI thread.
// It never calls drawScene/mainLoop or creates synthetic physics frames.
// The feature requires BOTH existing user opt-ins and remembers whether the
// Director was actively running BEFORE focus was lost, so an already-paused
// game must remain paused. Each focus-loss transition gets at most one resume.
struct FocusRecovery {
    bool pending = false;
    bool wasRunning = false;
    bool attempted = false;
    PlayLayer* level = nullptr; // identity only; NEVER dereference after transitions
    std::uint64_t manualPauseEpoch = 0;
    std::uint64_t focusLossEvents = 0;
    std::uint64_t restoreEvents = 0;
    std::uint64_t resumeAttempts = 0;
    std::uint64_t resumeCallsUnpaused = 0;
    std::int64_t lastResumeMs = 0;
};
// Exclusively accessed on game/UI thread via WndProc or authenticated RPC.
FocusRecovery focusRecovery;

bool backgroundControlArmed() {
    return backgroundPlayRequested.load() &&
        Mod::get()->getSettingValue<bool>("allow-background-play");
}

void markFocusLost() {
    ++focusRecovery.focusLossEvents;
    auto* director = cocos2d::CCDirector::sharedDirector();
    auto* play = PlayLayer::get();
    focusRecovery.level = play;
    focusRecovery.wasRunning = play && director && !director->isPaused();
    focusRecovery.manualPauseEpoch = nonUnfocusPauseRequests.load();
    focusRecovery.pending = backgroundControlArmed() && focusRecovery.wasRunning;
    focusRecovery.attempted = false;
}

void maybeRecoverDirectorPause() {
    if (!focusRecovery.pending || focusRecovery.attempted) return;
    if (!backgroundControlArmed() ||
        focusRecovery.manualPauseEpoch != nonUnfocusPauseRequests.load() ||
        !focusRecovery.level || PlayLayer::get() != focusRecovery.level) {
        focusRecovery.pending = false;
        return;
    }
    // No attempt when the Director is already running; keep the pending flag
    // because a later WM_SIZE/minimize or background callback may pause it.
    auto* director = cocos2d::CCDirector::sharedDirector();
    if (!director || !director->isPaused()) return;
    focusRecovery.attempted = true;
    focusRecovery.pending = false;
    ++focusRecovery.resumeAttempts;
    // Official Cocos method. Calling resume() does NOT restart a stopped
    // minimized window/render loop; the subsequent probe must confirm frames.
    director->resume();
    focusRecovery.lastResumeMs = std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::steady_clock::now().time_since_epoch()).count();
    if (!director->isPaused()) ++focusRecovery.resumeCallsUnpaused;
}

// The Geode main-thread task queue normally runs from Cocos's frame loop.
// GD can suspend that loop while not focused, even while the Win32 window
// thread continues processing messages. Install a Windows window subclass
// on that SAME thread in MenuLayer::init; it can service authenticated
// requests without requiring foreground focus or running a fake game frame.
// This does not keep gameplay/physics advancing when GD is suspended.
constexpr UINT_PTR PUMP_SUBCLASS_ID = 0x676d6454; // "gmdT"
std::atomic<HWND> pumpWindow{nullptr};
std::atomic<DWORD> pumpThreadId{0};
std::atomic<UINT> pumpMessage{0};
std::atomic<std::uint64_t> pumpDeliveries{0};
std::atomic<std::uint64_t> pumpCommands{0};
std::mutex mailboxMutex;
std::deque<std::weak_ptr<std::function<void()>>> mailbox;

void drainMailbox() {
    std::deque<std::weak_ptr<std::function<void()>>> jobs;
    {
        std::lock_guard guard(mailboxMutex);
        jobs.swap(mailbox);
    }
    for (auto& weak : jobs) {
        if (auto job = weak.lock()) {
            ++pumpCommands;
            (*job)(); // Same GD/Win32 UI thread; runOnce atomic prevents duplicates.
        }
    }
}

LRESULT CALLBACK bridgeSubclassProc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp,
                                     UINT_PTR subclassId, DWORD_PTR) {
    // WM_ACTIVATEAPP is a real window lifecycle signal, unlike guessing focus
    // from a screenshot. Do not interfere with its default delivery to GD.
    bool focusLost = msg == WM_ACTIVATEAPP && wp == FALSE;
    bool focusRestored = msg == WM_ACTIVATEAPP && wp != FALSE;
    bool minimized = msg == WM_SIZE && wp == SIZE_MINIMIZED;
    if (focusLost) markFocusLost();
    if (focusRestored) {
        ++focusRecovery.restoreEvents;
        focusRecovery.pending = false;
    }
    if (msg && msg == pumpMessage.load()) {
        if (::GetCurrentThreadId() == pumpThreadId.load()) {
            ++pumpDeliveries;
            // The engine might pause AFTER WM_ACTIVATEAPP processing. Our
            // existing UI-thread message also provides a deferred opportunity.
            maybeRecoverDirectorPause();
            drainMailbox();
        }
        return 0;
    }
    if (msg == WM_NCDESTROY) {
        focusRecovery.pending = false;
        pumpWindow.store(nullptr);
        pumpThreadId.store(0);
        ::RemoveWindowSubclass(hwnd, bridgeSubclassProc, subclassId);
    }
    auto result = ::DefSubclassProc(hwnd, msg, wp, lp);
    // Wait until the game's original window handler has processed the event.
    // Recover only an automatic Director pause, once per focus loss.
    if (focusLost || minimized) maybeRecoverDirectorPause();
    return result;
}

BOOL CALLBACK findOwnedThreadWindow(HWND hwnd, LPARAM value) {
    if (::GetWindow(hwnd, GW_OWNER) == nullptr &&
        (::IsWindowVisible(hwnd) || ::IsIconic(hwnd))) {
        *reinterpret_cast<HWND*>(value) = hwnd;
        return FALSE;
    }
    return TRUE;
}

void installMainThreadPump() {
    // MUST be invoked from game main thread (MenuLayer::init or Geode queue).
    auto const tid = ::GetCurrentThreadId();
    auto current = pumpWindow.load();
    if (current && ::IsWindow(current) && pumpThreadId.load() == tid) return;
    HWND hwnd = nullptr;
    ::EnumThreadWindows(tid, findOwnedThreadWindow, reinterpret_cast<LPARAM>(&hwnd));
    if (!hwnd || ::GetWindowThreadProcessId(hwnd, nullptr) != tid) {
        log::warn("gmdtool bridge: cannot find a game window on main thread");
        return;
    }
    auto message = ::RegisterWindowMessageW(L"gmdtool.runtime-bridge.main-pump.v1");
    if (!message || !::SetWindowSubclass(hwnd, bridgeSubclassProc, PUMP_SUBCLASS_ID, 0)) {
        log::warn("gmdtool bridge: Win32 main-thread subclass installation failed");
        return;
    }
    pumpThreadId.store(tid);
    pumpMessage.store(message);
    pumpWindow.store(hwnd);
    log::info("gmdtool bridge: Windows message pump installed (no focus change)");
}

// Win32 window operations are the only things the socket thread does besides
// transport and JSON. No Cocos / GD pointers cross threads. In particular,
// WM_NULL does NOT foreground the game or force physics/rendering to run.
struct WindowProbe {
    HWND hwnd = nullptr;
    bool visible = false;
    bool minimized = false;
    bool foreground = false;
};

BOOL CALLBACK findGameWindow(HWND candidate, LPARAM result) {
    DWORD processId = 0;
    ::GetWindowThreadProcessId(candidate, &processId);
    if (processId == ::GetCurrentProcessId() &&
        ::GetWindow(candidate, GW_OWNER) == nullptr &&
        (::IsWindowVisible(candidate) || ::IsIconic(candidate))) {
        *reinterpret_cast<HWND*>(result) = candidate;
        return FALSE;
    }
    return TRUE;
}

WindowProbe probeWindow() {
    WindowProbe probe;
    ::EnumWindows(&findGameWindow, reinterpret_cast<LPARAM>(&probe.hwnd));
    if (!probe.hwnd) return probe;
    probe.visible = ::IsWindowVisible(probe.hwnd) != FALSE;
    probe.minimized = ::IsIconic(probe.hwnd) != FALSE;
    DWORD foregroundProcess = 0;
    if (auto foreground = ::GetForegroundWindow())
        ::GetWindowThreadProcessId(foreground, &foregroundProcess);
    probe.foreground = foregroundProcess == ::GetCurrentProcessId();
    return probe;
}

matjson::Value windowAsJson(WindowProbe const& window) {
    return matjson::makeObject({
        {"found", window.hwnd != nullptr},
        {"foreground", window.foreground},
        {"minimized", window.minimized},
        {"visible", window.visible}
    });
}

bool requestNonActivatingWakeup() {
    // Prefer our registered, authenticated-command mailbox on GD's UI HWND;
    // unlike WM_NULL it actually runs the queued task from its WndProc.
    auto hwnd = pumpWindow.load();
    auto msg = pumpMessage.load();
    if (hwnd && msg && ::IsWindow(hwnd) &&
        ::PostMessageW(hwnd, msg, 0, 0) != FALSE) return true;
    // Before the subclass has been installed only a no-op wake is possible.
    auto window = probeWindow();
    return window.hwnd && ::PostMessageW(window.hwnd, WM_NULL, 0, 0) != FALSE;
}

std::int64_t monotonicMilliseconds() {
    return std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::steady_clock::now().time_since_epoch()).count();
}

matjson::Value transportPing() {
    return matjson::makeObject({
        {"protocol", 1}, {"bridge", "gmdtool-geode"},
        {"online", true}, {"main_thread_checked", false}
    });
}

matjson::Value transportDiagnostics() {
    auto now = monotonicMilliseconds();
    auto completedAt = counters.lastCompletedMs.load();
    auto updatedAt = counters.lastPostUpdateMs.load();
    auto result = matjson::makeObject({
        {"transport_ok", true}, {"main_thread_checked", false},
        {"queued", static_cast<std::int64_t>(counters.queued.load())},
        {"started", static_cast<std::int64_t>(counters.started.load())},
        {"completed", static_cast<std::int64_t>(counters.completed.load())},
        {"timed_out", static_cast<std::int64_t>(counters.timedOut.load())},
        {"post_update_count", static_cast<std::int64_t>(counters.postUpdates.load())}
    });
    result["main_thread_checked"] = counters.completed.load() > 0;
    result["main_thread_recent"] = completedAt > 0 && now - completedAt < 5000;
    result["window"] = windowAsJson(probeWindow());
    result["window_pump_installed"] = pumpWindow.load() != nullptr;
    result["window_pump_deliveries"] = static_cast<std::int64_t>(pumpDeliveries.load());
    result["window_pump_commands"] = static_cast<std::int64_t>(pumpCommands.load());
    result["main_thread_dispatch"] = "Geode queue + Win32 UI-thread message (at-most-once)";
    result["background_behavior"] = "opt-in unfocus-pause bypass; no forced game-loop";
    result["background_play_requested"] = backgroundPlayRequested.load();
    result["unfocus_pause_requests"] = static_cast<std::int64_t>(unfocusPauseRequests.load());
    result["unfocus_pause_suppressed"] = static_cast<std::int64_t>(unfocusPauseSuppressed.load());
    result["non_unfocus_pause_requests"] = static_cast<std::int64_t>(nonUnfocusPauseRequests.load());
    result["last_completed_ago_ms"] = completedAt ? matjson::Value(now - completedAt) : matjson::Value(nullptr);
    result["last_post_update_ago_ms"] = updatedAt ? matjson::Value(now - updatedAt) : matjson::Value(nullptr);
    return result;
}

// Count observations of PlayLayer::postUpdate, NOT physics ticks / TPS.
// All accesses to the scheduling state happen exclusively on GD's main thread.
struct InputEvent {
    std::uint64_t update;
    bool down;
    int button;
    bool player1;
};
struct RuntimeState {
    PlayLayer* owner = nullptr;
    std::uint64_t updates = 0;
    std::int64_t lastUpdateMs = 0; // per-level, unlike global transport health
    std::vector<InputEvent> inputs;
};
RuntimeState state;

// Lightweight, bounded Item-ID change tracing for AI debugging.
// Every access is on the game thread. Tracing never steps the simulation.
// A sample belongs to the PlayLayer postUpdate CALLBACK counter, NOT a physics tick.
constexpr std::size_t MAX_TRACE_IDS = 8;
constexpr std::size_t MAX_TRACE_SAMPLES = 256;
struct TraceSample {
    std::uint64_t update = 0;
    std::vector<int> values;
};
struct TraceState {
    bool active = false;
    std::uint64_t everyUpdates = 1;
    std::vector<int> ids;
    std::vector<int> lastValues;
    bool hasBaseline = false;
    std::deque<TraceSample> samples;
    std::uint64_t discarded = 0;
    std::uint64_t observedUpdates = 0;
    std::uint64_t lastSampleUpdate = 0;
    std::int64_t lastSampleMs = 0;
    std::int64_t lastChangeMs = 0;
};
TraceState trace;

void collectItemTrace(PlayLayer* play) {
    if (!trace.active || !play->m_effectManager ||
        (state.updates % trace.everyUpdates) != 0) return;
    ++trace.observedUpdates;
    trace.lastSampleUpdate = state.updates;
    trace.lastSampleMs = monotonicMilliseconds();
    std::vector<int> values;
    values.reserve(trace.ids.size());
    for (auto id : trace.ids) values.push_back(play->m_effectManager->countForItem(id));
    if (trace.hasBaseline && values == trace.lastValues) return;
    trace.lastValues = values;
    trace.hasBaseline = true;
    trace.lastChangeMs = trace.lastSampleMs;
    if (trace.samples.size() == MAX_TRACE_SAMPLES) {
        trace.samples.pop_front();
        ++trace.discarded;
    }
    trace.samples.push_back(TraceSample{state.updates, std::move(values)});
}

matjson::Value traceSummary() {
    matjson::Value ids = matjson::Value::array();
    for (auto id : trace.ids) ids.push(id);
    matjson::Value lastValues = matjson::Value::object();
    if (trace.hasBaseline) {
        for (std::size_t i = 0; i < trace.ids.size(); ++i)
            lastValues[std::to_string(trace.ids[i])] = trace.lastValues[i];
    }
    const auto now = monotonicMilliseconds();
    auto summary = matjson::makeObject({
        {"active", trace.active},
        {"ids", std::move(ids)},
        {"every_updates", static_cast<std::int64_t>(trace.everyUpdates)},
        {"observed_updates", static_cast<std::int64_t>(trace.observedUpdates)},
        {"buffered_changes", static_cast<int>(trace.samples.size())},
        {"discarded_changes", static_cast<std::int64_t>(trace.discarded)},
        {"level_update_callbacks", static_cast<std::int64_t>(state.updates)},
        {"samples_are_physics_ticks", false}
    });
    summary["has_baseline"] = trace.hasBaseline;
    summary["last_values"] = std::move(lastValues);
    summary["last_sample_update"] = trace.lastSampleMs
        ? matjson::Value(static_cast<std::int64_t>(trace.lastSampleUpdate)) : matjson::Value(nullptr);
    summary["last_sample_ago_ms"] = trace.lastSampleMs
        ? matjson::Value(now - trace.lastSampleMs) : matjson::Value(nullptr);
    summary["last_change_ago_ms"] = trace.lastChangeMs
        ? matjson::Value(now - trace.lastChangeMs) : matjson::Value(nullptr);
    summary["sampling_phase"] = "before_original_post_update";
    return summary;
}

void syncLevel(PlayLayer* layer) {
    if (state.owner != layer) {
        state = RuntimeState{};
        trace = TraceState{};
        state.owner = layer;
    }
}

// The scheduler deliberately does not modify the engine's dt, physics rate,
// frame pacing, or render path. Same-update ordering follows insertion order.
class $modify(GmdtoolBridgePlayLayer, PlayLayer) {
    void postUpdate(float dt) {
        syncLevel(this);
        ++state.updates;
        ++counters.postUpdates;
        const auto observedAt = monotonicMilliseconds();
        state.lastUpdateMs = observedAt;
        counters.lastPostUpdateMs.store(observedAt);
        auto it = state.inputs.begin();
        // Already sorted by requested update number; equal steps are stable.
        while (it != state.inputs.end() && it->update <= state.updates) {
            auto event = *it;
            it = state.inputs.erase(it);
            this->handleButton(event.down, event.button, event.player1);
        }
        // Snapshot immediately BEFORE the original postUpdate call. Item
        // changes in that call are observed on the next eligible callback.
        // Never read PlayLayer after calling its original update method:
        // some transitions may destroy/replace the active layer.
        collectItemTrace(this);
        PlayLayer::postUpdate(dt);
    }


    // Pause requests from other mods must not be mistaken for "manual" input.
    // Unless BOTH opt-ins are active, call the original unchanged. If active,
    // only pauseGame(true) (the unfocus flag) is bypassed. A hook that stops
    // the chain can still conflict with another pause mod, so do not enable
    // this during normal gameplay or alongside a competing unfocus mod.
    void pauseGame(bool unfocused) {
        if (unfocused) {
            ++unfocusPauseRequests;
            if (backgroundPlayRequested.load() &&
                Mod::get()->getSettingValue<bool>("allow-background-play")) {
                ++unfocusPauseSuppressed;
                return;
            }
        } else {
            ++nonUnfocusPauseRequests;
            // Never resume a pause explicitly requested after focus loss.
            focusRecovery.pending = false;
        }
        PlayLayer::pauseGame(unfocused);
    }

    void resetLevel() {
        syncLevel(this);
        state.updates = 0;
        state.inputs.clear(); // A reset invalidates any queued attempt inputs.
        trace = TraceState{}; // No stale values from the previous attempt.
        focusRecovery.pending = false;
        PlayLayer::resetLevel();
    }

    void onExit() {
        // Never let an experimental setting silently leak into the next level.
        backgroundPlayRequested.store(false);
        focusRecovery.pending = false;
        focusRecovery.level = nullptr;
        if (state.owner == this) {
            trace = TraceState{};
            state = RuntimeState{};
        }
        PlayLayer::onExit();
    }
};

// The menu is created with the game active, so this reliably captures the
// real GD UI thread and avoids assuming $on_mod(Loaded) runs on that thread.
class $modify(GmdtoolBridgeMenuLayer, MenuLayer) {
    bool init() {
        if (!MenuLayer::init()) return false;
        installMainThreadPump();
        return true;
    }
};

std::string makeToken() {
    std::random_device rd;
    std::ostringstream stream;
    stream << std::hex << std::setfill('0');
    for (int i = 0; i < 8; ++i) {
        stream << std::setw(4) << (rd() & 0xffff);
    }
    return stream.str();
}


// Inspect focus/pause/tick state using only supported Geode / Cocos APIs.
// This is NOT an assertion that the minimized renderer is still advancing.
matjson::Value readBackgroundStatus(PlayLayer* play) {
    if (play) syncLevel(play);  // keep per-level counters accurate even before first postUpdate
    auto director = cocos2d::CCDirector::sharedDirector();
    // Use a per-PlayLayer timestamp for gameplay freshness. Global counters
    // may refer to a previous level and otherwise give false positives.
    const auto lastLevel = play ? state.lastUpdateMs : std::int64_t(0);
    const auto lastGlobal = counters.lastPostUpdateMs.load();
    auto now = monotonicMilliseconds();
    auto window = probeWindow();
    return matjson::makeObject({
        {"playing", play != nullptr},
        {"setting_allowed", Mod::get()->getSettingValue<bool>("allow-background-play")},
        {"requested", backgroundPlayRequested.load()},
        {"director_paused", director ? director->isPaused() : false},
        {"window", windowAsJson(window)},
        {"unfocus_pause_requests", static_cast<std::int64_t>(unfocusPauseRequests.load())},
        {"unfocus_pause_suppressed", static_cast<std::int64_t>(unfocusPauseSuppressed.load())},
        {"non_unfocus_pause_requests", static_cast<std::int64_t>(nonUnfocusPauseRequests.load())},
        {"level_update_callbacks", static_cast<std::int64_t>(play ? state.updates : 0)},
        {"game_updates_recent", play && lastLevel > 0 && now >= lastLevel && now - lastLevel < 2000},
        {"post_update_count", static_cast<std::int64_t>(counters.postUpdates.load())},
        {"last_level_update_ago_ms", lastLevel ? matjson::Value(now - lastLevel) : matjson::Value(nullptr)},
        {"last_post_update_ago_ms", lastGlobal ? matjson::Value(now - lastGlobal) : matjson::Value(nullptr)},
        {"forces_game_loop", false},
        {"focus_loss_events", static_cast<std::int64_t>(focusRecovery.focusLossEvents)},
        {"focus_restore_events", static_cast<std::int64_t>(focusRecovery.restoreEvents)},
        {"director_resume_attempts", static_cast<std::int64_t>(focusRecovery.resumeAttempts)},
        {"director_resume_unpaused", static_cast<std::int64_t>(focusRecovery.resumeCallsUnpaused)},
        {"director_resume_pending", focusRecovery.pending},
        {"last_director_resume_ago_ms", focusRecovery.lastResumeMs
            ? matjson::Value(now - focusRecovery.lastResumeMs) : matjson::Value(nullptr)},
        {"note", "Opt-in focus-loss recovery: one Director resume attempt if running before focus loss; no forced frames. Game progress must be measured separately."}
    });
}

matjson::Value readStatus(PlayLayer* play) {
    auto result = matjson::makeObject({{"playing", play != nullptr}});
    if (!play) return result;
    syncLevel(play);
    result["background"] = readBackgroundStatus(play);
    result["update_callbacks"] = static_cast<std::int64_t>(state.updates);
    result["queued_inputs"] = static_cast<int>(state.inputs.size());
    result["percent"] = play->getCurrentPercent();
    result["player_dead"] = play->m_playerDied;
    if (auto player = play->m_player1) {
        auto pos = player->getPosition();
        result["player1"] = matjson::makeObject({{"x", pos.x}, {"y", pos.y}});
    }
    if (auto player = play->m_player2) {
        auto pos = player->getPosition();
        result["player2"] = matjson::makeObject({{"x", pos.x}, {"y", pos.y}});
    }
    return result;
}

matjson::Value readItems(PlayLayer* play, matjson::Value const& params, bool allowEmpty) {
    auto ids = params["ids"].asArray();
    if (!ids || (!allowEmpty && ids.unwrap().empty()) || ids.unwrap().size() > 128) {
        return matjson::makeObject({{"_bridge_error", "ids must be an array of up to 128 items"}});
    }
    auto manager = play->m_effectManager;
    if (!manager) {
        return matjson::makeObject({{"_bridge_error", "Effect manager not ready"}});
    }
    matjson::Value values = matjson::makeObject({});
    for (auto const& element : ids.unwrap()) {
        auto parsedId = element.asInt();
        if (!parsedId || parsedId.unwrap() < 1 || parsedId.unwrap() > 9999) {
            return matjson::makeObject({{"_bridge_error", "item IDs must be 1..9999"}});
        }
        auto id = static_cast<int>(parsedId.unwrap());
        values[std::to_string(id)] = manager->countForItem(id);
    }
    return matjson::makeObject({{"values", values}});
}

matjson::Value resultFor(matjson::Value const& request) {
    auto method = request["method"].asString().unwrapOr("");
    auto play = PlayLayer::get();
    if (method == "background_status") {
        return readBackgroundStatus(play);
    }
    if (method == "background_control") {
        // Main-thread only. Must explicitly opt in through Geode Settings too.
        auto enabled = request["params"]["enabled"].asBool();
        if (!enabled) {
            return matjson::makeObject({{"_bridge_error", "expected enabled:bool"}});
        }
        if (enabled.unwrap() && !play) {
            return matjson::makeObject({{"_bridge_error", "Start a level before enabling background play"}});
        }
        if (enabled.unwrap() && !Mod::get()->getSettingValue<bool>("allow-background-play")) {
            return matjson::makeObject({{"_bridge_error", "Enable 'Allow background level play (experimental)' in Geode mod settings first"}});
        }
        backgroundPlayRequested.store(enabled.unwrap());
        if (!enabled.unwrap()) focusRecovery.pending = false;
        return readBackgroundStatus(play);
    }
    if (method == "status") {
        return readStatus(play);
    }
    if (method == "runtime_probe") {
        // One read-only, main-thread-consistent observation for diagnostics.
        // Never advance frames, invoke inputs, or infer physics ticks.
        const auto& idValue = request["params"]["ids"];
        auto ids = idValue.asArray();
        if (!idValue.isNull() && (!ids || ids.unwrap().size() > MAX_TRACE_IDS))
            return matjson::makeObject({{"_bridge_error", "runtime_probe: ids must be an array of up to 8 items"}});
        if (ids) {
            std::vector<int> seen;
            for (auto const& value : ids.unwrap()) {
                auto id = value.asInt();
                if (!id || id.unwrap() < 1 || id.unwrap() > 9999 ||
                    std::find(seen.begin(), seen.end(), static_cast<int>(id.unwrap())) != seen.end())
                    return matjson::makeObject({{"_bridge_error", "runtime_probe: ids must be unique integers in 1..9999"}});
                seen.push_back(static_cast<int>(id.unwrap()));
            }
        }
        auto probe = readStatus(play);
        probe["probe_monotonic_ms"] = monotonicMilliseconds();
        probe["trace"] = play ? traceSummary() : matjson::makeObject({{"active", false}});
        probe["values"] = matjson::Value::object();
        if (play && ids && !ids.unwrap().empty()) {
            auto itemResult = readItems(play, request["params"], false);
            if (itemResult.contains("_bridge_error")) return itemResult;
            probe["values"] = itemResult["values"];
        }
        probe["consistency"] = "single_main_thread_request_not_physics_tick";
        return probe;
    }
    if (method == "snapshot" && !play) {
        auto result = readStatus(play);
        result["values"] = matjson::makeObject({});
        return result;
    }
    if (!play) {
        return matjson::makeObject({{"_bridge_error", "No active PlayLayer; open a level first"}});
    }
    // Initialize the per-layer state even before the first postUpdate callback.
    // In particular, trace_start must survive a subsequent status() call.
    syncLevel(play);
    if (method == "reset_level") {
        play->resetLevel();
        return matjson::makeObject({{"requested", true}});
    }
    if (method == "trace_start") {
        // A bounded, all-or-nothing validation pass; reject duplicate IDs.
        auto const& params = request["params"];
        auto ids = params["ids"].asArray();
        auto interval = params["every_updates"].asInt();
        auto step = params["every_updates"].isNull() ? std::int64_t(1)
             : interval ? static_cast<std::int64_t>(interval.unwrap()) : std::int64_t(-1);
        if (!ids || ids.unwrap().empty() || ids.unwrap().size() > MAX_TRACE_IDS ||
            step < 1 || step > 600) {
            return matjson::makeObject({{"_bridge_error", "trace_start: ids must be 1..8 IDs; every_updates must be 1..600"}});
        }
        std::vector<int> selected;
        for (auto const& element : ids.unwrap()) {
            auto value = element.asInt();
            if (!value || value.unwrap() < 1 || value.unwrap() > 9999 ||
                std::find(selected.begin(), selected.end(), static_cast<int>(value.unwrap())) != selected.end()) {
                return matjson::makeObject({{"_bridge_error", "trace_start: IDs must be unique integers in 1..9999"}});
            }
            selected.push_back(static_cast<int>(value.unwrap()));
        }
        if (!play->m_effectManager)
            return matjson::makeObject({{"_bridge_error", "effect manager is not ready"}});
        trace = TraceState{};
        trace.active = true;
        trace.everyUpdates = static_cast<std::uint64_t>(step);
        trace.ids = std::move(selected);
        return traceSummary();
    }
    if (method == "trace_status") return traceSummary();
    if (method == "trace_stop") {
        trace.active = false; // Keep buffered changes for a final read.
        return traceSummary();
    }
    if (method == "trace_read") {
        bool drain = request["params"]["drain"].asBool().unwrapOr(false);
        matjson::Value entries = matjson::Value::array();
        for (auto const& sample : trace.samples) {
            auto values = matjson::Value::object();
            for (std::size_t i = 0; i < trace.ids.size(); ++i)
                values[std::to_string(trace.ids[i])] = sample.values[i];
            entries.push(matjson::makeObject({
                {"update", static_cast<std::int64_t>(sample.update)},
                {"values", std::move(values)}
            }));
        }
        auto result = traceSummary();
        result["changes"] = std::move(entries);
        if (drain) trace.samples.clear();
        return result;
    }
    if (method == "input_queue_status") {
        syncLevel(play);
        return matjson::makeObject({
            {"update_callbacks", static_cast<std::int64_t>(state.updates)},
            {"queued_inputs", static_cast<int>(state.inputs.size())}
        });
    }
    if (method == "clear_inputs") {
        syncLevel(play);
        auto count = state.inputs.size();
        state.inputs.clear();
        return matjson::makeObject({{"cleared", static_cast<int>(count)}});
    }
    if (method == "schedule_inputs") {
        syncLevel(play);
        auto events = request["params"]["events"].asArray();
        if (!events || events.unwrap().empty() || events.unwrap().size() > 128 ||
            state.inputs.size() + events.unwrap().size() > 512) {
            return matjson::makeObject({{"_bridge_error", "events must have 1..128 entries; max 512 pending"}});
        }
        std::vector<InputEvent> batch;
        batch.reserve(events.unwrap().size());
        // Validate all entries before queuing any of them (atomic batch).
        for (auto const& entry : events.unwrap()) {
            auto update = entry["update"].asInt();
            auto down = entry["down"].asBool();
            auto button = entry["button"].asInt();
            auto player = entry["player"].asInt();
            if (!update || !down || !button || !player ||
                update.unwrap() <= static_cast<std::int64_t>(state.updates) ||
                update.unwrap() > static_cast<std::int64_t>(state.updates) + 100'000 ||
                button.unwrap() < 1 || button.unwrap() > 3 ||
                player.unwrap() < 1 || player.unwrap() > 2) {
                return matjson::makeObject({{"_bridge_error", "invalid update/down/button/player or update not in future"}});
            }
            batch.push_back({static_cast<std::uint64_t>(update.unwrap()),
                down.unwrap(), static_cast<int>(button.unwrap()), player.unwrap() == 1});
        }
        state.inputs.insert(state.inputs.end(), batch.begin(), batch.end());
        std::stable_sort(state.inputs.begin(), state.inputs.end(),
            [](InputEvent const& a, InputEvent const& b) { return a.update < b.update; });
        return matjson::makeObject({
            {"accepted", static_cast<int>(batch.size())},
            {"update_callbacks", static_cast<std::int64_t>(state.updates)},
            {"queued_inputs", static_cast<int>(state.inputs.size())}
        });
    }
    if (method == "items") {
        return readItems(play, request["params"], false);
    }
    if (method == "snapshot") {
        auto items = readItems(play, request["params"], true);
        if (items.contains("_bridge_error")) return items;
        auto snapshot = readStatus(play);
        snapshot["values"] = items["values"];
        return snapshot;
    }
    if (method == "input") {
        auto const& params = request["params"];
        auto down = params["down"].asBool();
        auto button = params["button"].asInt();
        auto player = params["player"].asInt();
        if (!down || !button || !player || button.unwrap() < 1 || button.unwrap() > 3 ||
            player.unwrap() < 1 || player.unwrap() > 2) {
            return matjson::makeObject({{"_bridge_error", "expected down:bool, button:1..3, player:1..2"}});
        }
        // The game's own input path; the moment this queued call runs is NOT a
        // guaranteed physics tick, unlike a future scheduled-replay feature.
        play->handleButton(down.unwrap(), static_cast<int>(button.unwrap()), player.unwrap() == 1);
        return matjson::makeObject({{"accepted", true}});
    }
    return matjson::makeObject({{"_bridge_error", "unknown method"}});
}

matjson::Value onRequest(matjson::Value const& request, std::string const& token) {
    auto id = request["id"];
    auto reply = matjson::makeObject({{"id", id}, {"ok", false}});
    if (request["token"].asString().unwrapOr("") != token) {
        reply["error"] = "authentication failed";
        return reply;
    }
    if (!request["method"].isString()) {
        reply["error"] = "method must be a string";
        return reply;
    }
    auto method = request["method"].asString().unwrapOr("");
    // Transport-only methods never touch GD/Cocos objects, so must not wait for
    // the main-thread queue. This is especially important when GD loses focus.
    if (method == "ping" || method == "bridge_health") {
        reply["ok"] = true;
        reply["result"] = method == "ping" ? transportPing() : transportDiagnostics();
        return reply;
    }
    // The network thread must never dereference any GD/Cocos object.
    auto promise = std::make_shared<std::promise<matjson::Value>>();
    auto future = promise->get_future();
    // A timed-out command should not mutate GD later just because it was
    // still waiting in the main-thread queue. A command that has already
    // *started* is not cancellable; callers must treat timeouts as uncertain.
    auto pending = std::make_shared<std::atomic_bool>(true);
    ++counters.queued;
    auto job = std::make_shared<std::function<void()>>([request, promise, pending] {
        if (!pending->exchange(false)) return; // timeout cancelled before start
        ++counters.started;
        matjson::Value result;
        try {
            result = resultFor(request);
        } catch (std::exception const& e) {
            result = matjson::makeObject({{"_bridge_error", e.what()}});
        } catch (...) {
            result = matjson::makeObject({{"_bridge_error", "unhandled main-thread exception"}});
        }
        counters.lastCompletedMs.store(monotonicMilliseconds());
        ++counters.completed;
        promise->set_value(std::move(result));
    });
    // Two *same-thread* execution opportunities. The mailbox can be drained
    // by our Win32 subclass even when Cocos's frame scheduler is suspended.
    // The atomic pending bit makes both execution paths at-most-once.
    {
        std::lock_guard guard(mailboxMutex);
        // Bound the fallback mailbox even if Cocos keeps holding canceled
        // jobs in its frozen main-thread queue. Any displaced job can still
        // complete on Cocos's original queue, or time out safely.
        if (mailbox.size() >= 128) mailbox.clear();
        mailbox.emplace_back(job);
    }
    geode::queueInMainThread([job] { (*job)(); });
    // Attempt to wake the host's Windows message pump without stealing focus.
    // Both the Geode queue and Windows message callback execute on the
    // verified game/UI thread; the socket thread never executes game code.
    const bool wakePosted = requestNonActivatingWakeup();
    if (future.wait_for(std::chrono::seconds(3)) != std::future_status::ready) {
        pending->store(false);
        ++counters.timedOut;
        auto window = probeWindow();
        std::string reason = "main-thread queue not serviced";
        if (window.minimized) reason += "; GD window minimized";
        else if (window.hwnd && !window.foreground) reason += "; GD window is not foreground";
        else if (!window.hwnd) reason += "; game window not found";
        reason += pumpWindow.load() ? "; UI message pump registered" : "; UI message pump not installed";
        reason += wakePosted ? "; window message posted" : "; window message not posted";
        reply["error"] = reason + "; use bridge-health for diagnostics";
        return reply;
    }
    auto result = future.get();
    if (result.contains("_bridge_error")) {
        reply["error"] = result["_bridge_error"];
        return reply;
    }
    reply["ok"] = true;
    reply["result"] = result;
    return reply;
}

// Only protocol parsing and authentication run on the worker thread.
// Every GD / Cocos call happens in resultFor() on the game main thread,
// either through Geode's normal queue or the verified Windows UI callback.
std::string handleWireRequest(std::string const& line, std::string const& token) {
    matjson::Value reply = matjson::makeObject({
        {"id", nullptr}, {"ok", false}, {"error", "malformed request"}
    });
    try {
        auto parsed = matjson::parse(line);
        if (parsed && parsed.unwrap().isObject()) {
            reply = onRequest(parsed.unwrap(), token);
        }
    } catch (std::exception const& e) {
        reply["error"] = e.what();
    }
    return reply.dump(matjson::NO_INDENTATION) + "\n";
}

// jthread owns the server. Never detach a worker running code from our DLL:
// its stop token and bounded socket waits allow a clean unload.
std::jthread serverThread;
} // anonymous namespace

$on_mod(Loaded) {
    // If Loaded executes before MenuLayer is created this task gets another
    // chance to install the pump when the main-thread scheduler is live.
    geode::queueInMainThread([] { installMainThreadPump(); });
    if (!Mod::get()->getSettingValue<bool>("enabled")) return;
    auto token = makeToken();
    auto session = Mod::get()->getSaveDir() / "bridge-session.json";
    std::error_code error;
    std::filesystem::create_directories(session.parent_path(), error);
    if (error) {
        log::error("gmdtool bridge: cannot create save directory: {}", error.message());
        return;
    }
    std::filesystem::remove(session, error);
    log::info("gmdtool bridge session descriptor (when ready): {}", session.string());
    auto descriptor = matjson::makeObject({
        {"protocol", 1}, {"host", "127.0.0.1"}, {"port", PORT}, {"token", token}
    }).dump(matjson::NO_INDENTATION);
    serverThread = std::jthread([token = std::move(token), session, descriptor](std::stop_token stop) {
        gmdtool::transport::runLocalServer(stop, PORT, session, descriptor,
            [token](std::string const& line) { return handleWireRequest(line, token); });
    });
}
#endif
